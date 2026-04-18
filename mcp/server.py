"""
SDRF Skills MCP Server

Implements tools for SDRF annotation workflow:
- PRIDE: project metadata, file list
- Europe PMC: article search, metadata, full text
- NCBI: PMID→PMCID for get_project_details
- Preprints: bioRxiv/medRxiv search
- OLS: ontology term search for SDRF column annotation
"""

import os
import sys
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from fastmcp import FastMCP
import httpx

mcp = FastMCP(
    "sdrf-pride-pmc",
    instructions="PRIDE, Europe PMC, OLS ontology, and preprint tools for SDRF annotation workflow",
)

PRIDE_BASE = "https://www.ebi.ac.uk/pride/ws/archive/v2"
EUROPE_PMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
EUROPE_PMC_FTP_BASE = "https://ftp.ebi.ac.uk/pub/databases/pmc/pdf/OA"
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_PMC_OA_FCGI = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
OLS_BASE = "https://www.ebi.ac.uk/ols4/api"
UNPAYWALL_BASE = "https://api.unpaywall.org/v2"


def _pmid_to_pmcid(client: httpx.Client, pmid: str) -> str | None:
    """通过 NCBI elink 从 PMID 获取 PMCID。"""
    if not pmid or not str(pmid).strip():
        return None
    try:
        r = client.get(
            f"{NCBI_BASE}/elink.fcgi",
            params={"dbfrom": "pubmed", "db": "pmc", "id": pmid, "retmode": "json"},
        )
        if r.status_code != 200:
            return None
        j = r.json()
        for linkset in j.get("linksets", []):
            for ld in linkset.get("linksetdbs", []):
                if ld.get("linkname") == "pubmed_pmc":
                    ids_out = ld.get("links", [])
                    if ids_out:
                        v = ids_out[0]
                        return f"PMC{v}" if not str(v).upper().startswith("PMC") else str(v)
        return None
    except Exception:
        return None


# --- 1.1 Get PRIDE project metadata ---
@mcp.tool()
def get_project_details(project_accession: str) -> dict:
    """
    Get PRIDE project metadata by accession (e.g., PXD012345).
    Returns: organism, instruments, modifications, publications (PMID/PMCID/DOI), file count, description.
    """
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(f"{PRIDE_BASE}/projects/{project_accession}")
        resp.raise_for_status()
        data = resp.json()

        # Extract key fields
        organisms = [o.get("name", "") for o in data.get("organisms", [])]
        instruments = [i.get("name", "") for i in data.get("instruments", [])]
        mods = [m.get("name", "") for m in data.get("identifiedPTMStrings", [])]
        refs = data.get("references", [])
        pmids = [str(r.get("pubmedID", "")) for r in refs if r.get("pubmedID")]
        dois = [r.get("doi", "") for r in refs if r.get("doi")]

        # PMID -> PMCID 转换（与 convert_article_ids 逻辑一致）
        pmcids = [_pmid_to_pmcid(client, p) for p in pmids]

    return {
        "accession": data.get("accession"),
        "title": data.get("title"),
        "description": data.get("projectDescription"),
        "organism": organisms,
        "instruments": instruments,
        "modifications": mods,
        "publications": {
            "pmids": pmids,
            "pmcids": pmcids,
            "dois": [d for d in dois if d],
            "references": [r.get("referenceLine", "") for r in refs],
        },
        "keywords": data.get("keywords", []),
    }


# --- 1.2 Get project file list ---
RAW_LIKE_CATEGORIES = {"RAW", "SWIFF"}


@mcp.tool()
def get_project_files(project_accession: str) -> dict:
    """
    Get file list for a PRIDE project.
    Returns: rawfile_count (RAW or SWIFF), raw_file_names, other_files_names.
    """
    url = f"{PRIDE_BASE}/projects/{project_accession}/files"
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()

    files = data if isinstance(data, list) else data.get("content", []) if isinstance(data, dict) else []

    raw_file_names = []
    other_files_names = []
    for f in files:
        name = f.get("fileName", "")
        if not name:
            continue
        cat = f.get("fileCategory", {})
        ftype = (cat.get("value", "") if isinstance(cat, dict) else str(cat)).upper()
        if ftype in RAW_LIKE_CATEGORIES:
            raw_file_names.append(name)
        else:
            other_files_names.append(name)

    return {
        "project_accession": project_accession,
        "rawfile_count": len(raw_file_names),
        "raw_file_names": raw_file_names,
        "other_files_names": other_files_names,
    }


def _europe_pmc_ftp_zip_url(pmcid: str) -> str:
    """根据 PMCID 构建 Europe PMC FTP zip 的 URL。目录规则: PMCxxxx + 数字部分末 3 位。"""
    num = str(pmcid).upper().replace("PMC", "", 1).strip()
    last3 = num[-3:].zfill(3) if len(num) >= 3 else num.zfill(3)
    return f"{EUROPE_PMC_FTP_BASE}/PMCxxxx{last3}/{pmcid.upper()}.zip"


def _download_pdf_from_europe_pmc_ftp(
    client: httpx.Client, pmcid: str, out_dir: Path
) -> str | None:
    """
    从 Europe PMC FTP 下载 OA 子集的 zip，解压得到 PDF 并保存。
    仅对 OA 子集文章有效。返回本地 PDF 路径，失败返回 None。
    """
    zip_url = _europe_pmc_ftp_zip_url(pmcid)
    try:
        resp = client.get(zip_url, timeout=60.0)
        if resp.status_code != 200 or not resp.content:
            return None
        zip_path = out_dir / f"{pmcid.upper()}.zip"
        zip_path.write_bytes(resp.content)
        with zipfile.ZipFile(zip_path, "r") as zf:
            pdf_names = [n for n in zf.namelist() if n.lower().endswith(".pdf")]
            if not pdf_names:
                zip_path.unlink(missing_ok=True)
                return None
            pdf_name = pdf_names[0]
            pdf_data = zf.read(pdf_name)
            local_pdf = out_dir / f"{pmcid.upper()}.pdf"
            local_pdf.write_bytes(pdf_data)
        zip_path.unlink(missing_ok=True)
        return str(local_pdf)
    except Exception:
        return None


def _ncbi_ftp_href_to_https(href: str) -> str:
    """NCBI PMC OA 常返回 ftp://ftp.ncbi.nlm.nih.gov/...，改用 HTTPS 以便 httpx 下载。"""
    if href.startswith("ftp://ftp.ncbi.nlm.nih.gov/"):
        return "https://ftp.ncbi.nlm.nih.gov/" + href[len("ftp://ftp.ncbi.nlm.nih.gov/") :]
    if href.startswith("ftp://"):
        return href.replace("ftp://", "https://", 1)
    return href


def _parse_ncbi_oa_tgz_href(xml_text: str) -> str | None:
    """从 NCBI oa.fcgi 返回的 XML 中解析 format=tgz 的 link href。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    for link in root.iter("link"):
        if link.get("format") == "tgz" and link.get("href"):
            return link.get("href")
    return None


def _tar_extractall_compat(tf: tarfile.TarFile, path: Path) -> None:
    """兼容 3.10+；3.12+ 使用 data filter 降低路径穿越风险。"""
    if sys.version_info >= (3, 12):
        tf.extractall(path, filter="data")
    else:
        tf.extractall(path)


def _download_ncbi_pmc_oa_package(
    client: httpx.Client, pmcid: str, pdf_out_dir: Path
) -> tuple[str | None, str | None]:
    """
    查询 NCBI PMC OA API，下载 tgz 并解压到 pdf_out_dir / {PMCID}/。
    返回 (oa 包中的 tgz 原始 href, 解压目录的绝对路径)；无 OA 记录或失败时相应为 None。
    """
    num = str(pmcid).upper().replace("PMC", "", 1).strip()
    if not num:
        return None, None
    pmc_upper = f"PMC{num}"

    try:
        resp = client.get(
            NCBI_PMC_OA_FCGI,
            params={"id": pmc_upper},
            timeout=60.0,
        )
        if resp.status_code != 200:
            return None, None
        href = _parse_ncbi_oa_tgz_href(resp.text)
        if not href:
            return None, None
    except Exception:
        return None, None

    pkg_dir = (pdf_out_dir / pmc_upper).resolve()
    pkg_dir.mkdir(parents=True, exist_ok=True)

    download_url = _ncbi_ftp_href_to_https(href)
    try:
        r = client.get(download_url, timeout=180.0, follow_redirects=True)
        if r.status_code != 200 or not r.content:
            return href, None
        tgz_name = href.rstrip("/").split("/")[-1] or f"{pmc_upper}.tar.gz"
        tgz_path = pkg_dir / tgz_name
        tgz_path.write_bytes(r.content)
        with tarfile.open(tgz_path, "r:gz") as tf:
            _tar_extractall_compat(tf, pkg_dir)
        tgz_path.unlink(missing_ok=True)
        return href, str(pkg_dir)
    except Exception:
        return href, None


def _extract_pdf_url(r: dict) -> str | None:
    """从 Europe PMC 结果中提取 PDF URL。"""
    ft_list = r.get("fullTextUrlList", {})
    if isinstance(ft_list, dict):
        urls = ft_list.get("fullTextUrl", [])
    else:
        urls = []
    if not isinstance(urls, list):
        urls = [urls] if urls else []
    for u in urls:
        if isinstance(u, dict) and u.get("documentStyle") == "pdf":
            return u.get("url")
    return None


# --- 1.3a Get article metadata by PMID (含 PDF 链接) ---
@mcp.tool()
def get_article_by_pmid(pmids: list[str]) -> list[dict]:
    """
    Get article metadata by PMID(s). Attempts to find PDF link via Europe PMC.
    Returns: pmid, pmcid, doi, title, authors, abstract, journal, year, pubmed_url, doi_url, pdf_url, inPMC, isOpenAccess.
    """
    results = []
    with httpx.Client(timeout=30.0) as client:
        for pmid in pmids:
            pmid = str(pmid).strip()
            if not pmid or pmid == "0":
                continue

            url = f"{EUROPE_PMC_BASE}/search"
            params = {"query": f"EXT_ID:{pmid}", "format": "json", "pageSize": 1, "resultType": "core"}
            try:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                j = resp.json()
            except Exception as e:
                results.append({"pmid": pmid, "error": str(e)})
                continue

            hits = j.get("resultList", {}).get("result", [])
            if not hits:
                results.append({
                    "pmid": pmid,
                    "pmcid": None,
                    "doi": None,
                    "title": None,
                    "authors": None,
                    "abstract": "",
                    "journal": None,
                    "year": None,
                    "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "doi_url": None,
                    "pdf_url": None,
                    "inPMC": False,
                    "isOpenAccess": False,
                })
                continue

            r = hits[0]
            doi = r.get("doi")
            results.append({
                "pmid": pmid,
                "pmcid": r.get("pmcid"),
                "doi": doi,
                "title": r.get("title"),
                "authors": r.get("authorString"),
                "journal": r.get("journalTitle"),
                "year": r.get("pubYear"),
                "abstract": r.get("abstractText", "") or "",
                "inPMC": r.get("inPMC") == "Y",
                "isOpenAccess": r.get("isOpenAccess") == "Y",
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "doi_url": f"https://doi.org/{doi}" if doi else None,
                "pdf_url": _extract_pdf_url(r),
            })
    return results


# --- 1.3d Get article by PMCID (含 Europe PMC FTP PDF + NCBI PMC OA 包) ---
@mcp.tool()
def get_article_by_pmcid(pmc_ids: list[str], output_dir: str | None = None) -> list[dict]:
    """
    Get article metadata by PMCID(s). Attempts: (1) PDF from Europe PMC FTP OA subset;
    (2) full OA package from NCBI oa.fcgi (tgz → extract under output_dir/{PMCID}/).
    Returns: pmid, pmcid, doi, title, authors, abstract, journal, year, pubmed_url, doi_url,
    pdf_url, local_path, ncbi_oa_ftp_href, ncbi_oa_local_dir, inPMC, isOpenAccess.
    output_dir: base directory (default: mcp/pdf). PDF file in output_dir; NCBI OA under output_dir/{PMCID}/.
    """
    out_path = Path(output_dir if output_dir is not None else DEFAULT_PDF_DIR).resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    results = []
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for pmc_id in pmc_ids:
            raw_id = str(pmc_id).strip()
            clean_id = raw_id.replace("PMC", "", 1) if raw_id.upper().startswith("PMC") else raw_id
            if not clean_id:
                continue
            pmc_full = f"PMC{clean_id}" if not raw_id.upper().startswith("PMC") else raw_id

            ncbi_oa_ftp_href, ncbi_oa_local_dir = _download_ncbi_pmc_oa_package(
                client, pmc_full, out_path
            )

            url = f"{EUROPE_PMC_BASE}/search"
            params = {"query": f"PMCID:{pmc_full}", "format": "json", "pageSize": 1, "resultType": "core"}
            try:
                resp = client.get(url, params=params)
                if resp.status_code != 200:
                    results.append(
                        {
                            "pmid": None,
                            "pmcid": pmc_full,
                            "doi": None,
                            "title": None,
                            "authors": None,
                            "abstract": "",
                            "journal": None,
                            "year": None,
                            "pubmed_url": None,
                            "doi_url": None,
                            "pdf_url": None,
                            "local_path": None,
                            "ncbi_oa_ftp_href": ncbi_oa_ftp_href,
                            "ncbi_oa_local_dir": ncbi_oa_local_dir,
                            "inPMC": False,
                            "isOpenAccess": False,
                            "error": f"HTTP {resp.status_code}",
                        }
                    )
                    continue
                j = resp.json()
            except Exception as e:
                results.append(
                    {
                        "pmid": None,
                        "pmcid": pmc_full,
                        "doi": None,
                        "title": None,
                        "authors": None,
                        "abstract": "",
                        "journal": None,
                        "year": None,
                        "pubmed_url": None,
                        "doi_url": None,
                        "pdf_url": None,
                        "local_path": None,
                        "ncbi_oa_ftp_href": ncbi_oa_ftp_href,
                        "ncbi_oa_local_dir": ncbi_oa_local_dir,
                        "inPMC": False,
                        "isOpenAccess": False,
                        "error": str(e),
                    }
                )
                continue

            hits = j.get("resultList", {}).get("result", [])
            if not hits:
                results.append(
                    {
                        "pmid": None,
                        "pmcid": pmc_full,
                        "doi": None,
                        "title": None,
                        "authors": None,
                        "abstract": "",
                        "journal": None,
                        "year": None,
                        "pubmed_url": None,
                        "doi_url": None,
                        "pdf_url": None,
                        "local_path": None,
                        "ncbi_oa_ftp_href": ncbi_oa_ftp_href,
                        "ncbi_oa_local_dir": ncbi_oa_local_dir,
                        "inPMC": False,
                        "isOpenAccess": False,
                        "error": "Not found",
                    }
                )
                continue

            r = hits[0]
            pmid = r.get("pmid")
            doi = r.get("doi")
            pdf_url = _extract_pdf_url(r)
            local_path = _download_pdf_from_europe_pmc_ftp(client, pmc_full, out_path)
            results.append(
                {
                    "pmid": pmid,
                    "pmcid": r.get("pmcid") or pmc_full,
                    "doi": doi,
                    "title": r.get("title"),
                    "authors": r.get("authorString"),
                    "journal": r.get("journalTitle"),
                    "year": r.get("pubYear"),
                    "abstract": r.get("abstractText", "") or "",
                    "inPMC": r.get("inPMC") == "Y",
                    "isOpenAccess": r.get("isOpenAccess") == "Y",
                    "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
                    "doi_url": f"https://doi.org/{doi}" if doi else None,
                    "pdf_url": pdf_url,
                    "local_path": local_path,
                    "ncbi_oa_ftp_href": ncbi_oa_ftp_href,
                    "ncbi_oa_local_dir": ncbi_oa_local_dir,
                }
            )
    return results


# --- 1.3c Get article metadata and PDF by DOI ---
@mcp.tool()
def get_article_by_doi(dois: list[str]) -> list[dict]:
    """
    Get article metadata and PDF link by DOI(s).
    Uses Europe PMC for metadata; attempts to find PDF from fullTextUrlList.
    Returns: doi, pmid, pmcid, title, authors, abstract, journal, year, pubmed_url, doi_url, pdf_url, inPMC, isOpenAccess.
    """
    results = []
    with httpx.Client(timeout=30.0) as client:
        for doi in dois:
            doi = str(doi).strip()
            if not doi:
                continue
            if not doi.startswith("10."):
                doi = f"10.{doi}" if "." in doi else doi

            url = f"{EUROPE_PMC_BASE}/search"
            params = {"query": f"DOI:{doi}", "format": "json", "pageSize": 1, "resultType": "core"}
            try:
                resp = client.get(url, params=params)
                if resp.status_code != 200:
                    results.append({"doi": doi, "error": f"HTTP {resp.status_code}"})
                    continue
                j = resp.json()
            except Exception as e:
                results.append({"doi": doi, "error": str(e)})
                continue

            hits = j.get("resultList", {}).get("result", [])
            if not hits:
                results.append({
                    "doi": doi,
                    "pmid": None,
                    "pmcid": None,
                    "title": None,
                    "authors": None,
                    "abstract": "",
                    "journal": None,
                    "year": None,
                    "pubmed_url": None,
                    "doi_url": f"https://doi.org/{doi}",
                    "pdf_url": None,
                    "inPMC": False,
                    "isOpenAccess": False,
                })
                continue

            r = hits[0]
            pmid = r.get("pmid")
            results.append({
                "doi": doi,
                "pmid": pmid,
                "pmcid": r.get("pmcid"),
                "title": r.get("title"),
                "authors": r.get("authorString"),
                "journal": r.get("journalTitle"),
                "year": r.get("pubYear"),
                "abstract": r.get("abstractText", "") or "",
                "inPMC": r.get("inPMC") == "Y",
                "isOpenAccess": r.get("isOpenAccess") == "Y",
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
                "doi_url": f"https://doi.org/{doi}",
                "pdf_url": _extract_pdf_url(r),
            })
    return results


def _parse_identifier(s: str) -> tuple[str, str] | None:
    """解析 identifier，返回 (type, value)，type 为 'doi' 或 'pmid'。"""
    s = str(s).strip()
    if not s:
        return None
    s_lower = s.lower()
    if "doi.org/" in s_lower:
        idx = s_lower.find("doi.org/")
        doi = s[idx + 8 :].split("?", 1)[0].strip("/")
        return ("doi", doi) if doi else None
    if "pubmed.ncbi.nlm.nih.gov" in s_lower or "pubmed.gov" in s_lower:
        parts = s.replace("?", "/").rstrip("/").split("/")
        for p in reversed(parts):
            if p.isdigit():
                return ("pmid", p)
        return None
    if s.startswith("10.") or (s[0].isdigit() and "/" in s and "." in s.split("/")[0]):
        return ("doi", s.split("?", 1)[0])
    if s.isdigit():
        return ("pmid", s)
    if s.upper().startswith("PMC"):
        return None
    return ("doi", s)


def _doi_to_subdir_name(doi: str) -> str:
    """将 DOI 转为安全的子目录名（用于 pdf/{subdir}/）。"""
    return doi.replace("/", "_").replace(":", "_").strip()


def _unpaywall_save_dir(out_path: Path, parsed_type: str, pmid: str | None, doi: str) -> Path:
    """
    按输入类型决定保存目录：PMID/PubMed URL → pdf/{PMID}/；DOI 或 doi.org 链接 → pdf/{sanitized_doi}/。
    """
    if parsed_type == "pmid" and pmid:
        return out_path / pmid
    return out_path / _doi_to_subdir_name(doi)


# MCP 目录下的 pdf 子目录为默认保存路径
DEFAULT_PDF_DIR = Path(__file__).resolve().parent / "pdf"


# --- 1.3f Get PDF via Unpaywall 并下载到本地 ---
@mcp.tool()
def get_pdf_by_unpaywall(identifiers: list[str], output_dir: str | None = None) -> list[dict]:
    """
    Find OA PDF via Unpaywall and download to local. Accepts DOI, PMID, doi_url, or pubmed_url.
    For PMID: resolves to DOI via Europe PMC first. When Unpaywall has no pdf_url, falls back to Europe PMC PDF.
    Returns: identifier, doi, pmid, pdf_url, local_path, oa_status, license, host_type.
    output_dir: base directory (default: mcp/pdf). Saves as output_dir/{PMID}/fulltext.pdf when input is
    PMID/PubMed URL; otherwise output_dir/{sanitized_doi}/fulltext.pdf (DOI characters / and : → _).
    """
    email = os.environ.get("UNPAYWALL_EMAIL", "unpaywall@sdrf-skills.local")
    out_path = Path(output_dir if output_dir is not None else DEFAULT_PDF_DIR).resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    results = []

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for raw in identifiers:
            parsed = _parse_identifier(raw)
            if not parsed:
                results.append({
                    "identifier": raw,
                    "doi": None,
                    "pmid": None,
                    "pdf_url": None,
                    "local_path": None,
                    "oa_status": None,
                    "license": None,
                    "host_type": None,
                    "error": "Could not parse identifier (need DOI or PMID/URL)",
                })
                continue

            typ, val = parsed
            save_layout_type = typ  # PMID 走按 PMID 分目录；DOI/doi_url 走按 DOI 分目录
            doi = val if typ == "doi" else None
            pmid = val if typ == "pmid" else None

            if typ == "pmid":
                try:
                    url = f"{EUROPE_PMC_BASE}/search"
                    params = {"query": f"EXT_ID:{val}", "format": "json", "pageSize": 1, "resultType": "core"}
                    resp = client.get(url, params=params)
                    if resp.status_code != 200:
                        results.append({
                            "identifier": raw, "doi": None, "pmid": val,
                            "pdf_url": None, "local_path": None, "oa_status": None, "license": None, "host_type": None,
                            "error": f"Europe PMC HTTP {resp.status_code}",
                        })
                        continue
                    j = resp.json()
                    hits = j.get("resultList", {}).get("result", [])
                    if not hits:
                        results.append({
                            "identifier": raw, "doi": None, "pmid": val,
                            "pdf_url": None, "local_path": None, "oa_status": None, "license": None, "host_type": None,
                            "error": "PMID not found in Europe PMC",
                        })
                        continue
                    doi = hits[0].get("doi")
                    if not doi:
                        results.append({
                            "identifier": raw, "doi": None, "pmid": val,
                            "pdf_url": None, "local_path": None, "oa_status": None, "license": None, "host_type": None,
                            "error": "No DOI for this PMID",
                        })
                        continue
                except Exception as e:
                    results.append({
                        "identifier": raw, "doi": None, "pmid": val,
                        "pdf_url": None, "local_path": None, "oa_status": None, "license": None, "host_type": None,
                        "error": str(e),
                    })
                    continue

            if not doi:
                results.append({
                    "identifier": raw, "doi": None, "pmid": pmid,
                    "pdf_url": None, "local_path": None, "oa_status": None, "license": None, "host_type": None,
                    "error": "No DOI to query Unpaywall",
                })
                continue

            pdf_url = None
            oa_status = "closed"
            license_val = None
            host_type = None

            try:
                resp = client.get(f"{UNPAYWALL_BASE}/{doi}", params={"email": email})
                if resp.status_code == 200:
                    j = resp.json()
                    best = j.get("best_oa_location") or {}
                    pdf_url = best.get("url_for_pdf")
                    oa_status = j.get("oa_status") or "closed"
                    license_val = best.get("license")
                    host_type = best.get("host_type")
            except Exception:
                pass

            if not pdf_url:
                try:
                    epmc_resp = client.get(
                        f"{EUROPE_PMC_BASE}/search",
                        params={"query": f"DOI:{doi}", "format": "json", "pageSize": 1, "resultType": "core"},
                    )
                    if epmc_resp.status_code == 200:
                        hits = epmc_resp.json().get("resultList", {}).get("result", [])
                        if hits:
                            pdf_url = _extract_pdf_url(hits[0])
                except Exception:
                    pass

            if not pdf_url:
                results.append({
                    "identifier": raw,
                    "doi": doi,
                    "pmid": pmid,
                    "pdf_url": None,
                    "local_path": None,
                    "oa_status": oa_status,
                    "license": license_val,
                    "host_type": host_type,
                    "error": "No PDF URL found (Unpaywall and Europe PMC)",
                })
                continue

            local_path = None
            headers = {"User-Agent": "SDRF-Skills-MCP/1.0 (https://github.com/sdrf-community)"}
            try:
                pdf_resp = client.get(pdf_url, headers=headers)
                if pdf_resp.status_code == 200 and pdf_resp.content:
                    item_dir = _unpaywall_save_dir(out_path, save_layout_type, pmid, doi)
                    item_dir.mkdir(parents=True, exist_ok=True)
                    local_file = item_dir / "fulltext.pdf"
                    local_file.write_bytes(pdf_resp.content)
                    local_path = str(local_file)
            except Exception as e:
                results.append({
                    "identifier": raw,
                    "doi": doi,
                    "pmid": pmid,
                    "pdf_url": pdf_url,
                    "local_path": None,
                    "oa_status": oa_status,
                    "license": license_val,
                    "host_type": host_type,
                    "error": f"Download failed: {e}",
                })
                continue

            results.append({
                "identifier": raw,
                "doi": doi,
                "pmid": pmid,
                "pdf_url": pdf_url,
                "local_path": local_path,
                "oa_status": oa_status,
                "license": license_val,
                "host_type": host_type,
            })
    return results


# --- 1.3e Search Europe PMC ---
@mcp.tool()
def search_europepmc(query: str, page_size: int = 10) -> dict:
    """
    Search Europe PMC for articles.
    Use query like "PXD012345" to find papers mentioning a PRIDE accession.
    """
    url = f"{EUROPE_PMC_BASE}/search"
    params = {"query": query, "format": "json", "pageSize": page_size}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        j = resp.json()
    hits = j.get("resultList", {}).get("result", [])
    return {
        "hitCount": j.get("hitCount", 0),
        "results": [
            {
                "pmid": r.get("pmid"),
                "pmcid": r.get("pmcid"),
                "doi": r.get("doi"),
                "title": r.get("title"),
                "authors": r.get("authorString"),
                "journal": r.get("journalTitle"),
                "year": r.get("pubYear"),
                "abstract": (r.get("abstractText") or ""),
                "inPMC": r.get("inPMC") == "Y",
            }
            for r in hits
        ],
    }


# --- 1.3g Search preprints ---
@mcp.tool()
def search_preprints(query: str, page_size: int = 10) -> dict:
    """
    Search bioRxiv/medRxiv preprints via Europe PMC.
    Use title keywords from PRIDE project description when no PMID is found.
    Europe PMC indexes bioRxiv and medRxiv preprints.
    """
    # Europe PMC: filter by preprint source (BIO = bioRxiv, MED = medRxiv)
    europmc_query = f'({query}) AND (SRC:bio OR SRC:med)'
    url = f"{EUROPE_PMC_BASE}/search"
    params = {"query": europmc_query, "format": "json", "pageSize": page_size}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        j = resp.json()
    hits = j.get("resultList", {}).get("result", [])
    return {
        "hitCount": j.get("hitCount", 0),
        "results": [
            {
                "pmid": r.get("pmid"),
                "pmcid": r.get("pmcid"),
                "doi": r.get("doi"),
                "title": r.get("title"),
                "authors": r.get("authorString"),
                "source": r.get("source"),
                "year": r.get("pubYear"),
                "abstract": (r.get("abstractText") or ""),
            }
            for r in hits
        ],
    }


# --- 4.3 Search OLS for ontology terms ---
@mcp.tool()
def search_ontology_classes(query: str, ontology_id: str, page_size: int = 10) -> dict:
    """
    Search OLS (Ontology Lookup Service) for ontology terms/classes.
    ontology_id: ncbitaxon, uberon, bto, cl, clo, efo, mondo, doid, ncit, pato,
    pride, ms, unimod, mod, chebi, hancestro, envo, po, fbbt, wbbt, zfa, gaz, xlmod, go.
    Returns label, accession (obo_id), description, synonyms.
    """
    url = f"{OLS_BASE}/search"
    params = {
        "q": query,
        "ontology": ontology_id.lower().strip(),
        "rows": min(page_size, 50),
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        j = resp.json()

    docs = j.get("response", {}).get("docs", [])
    num_found = j.get("response", {}).get("numFound", 0)

    results = []
    for d in docs:
        results.append({
            "label": d.get("label"),
            "accession": d.get("obo_id"),
            "iri": d.get("iri"),
            "ontology": d.get("ontology_prefix") or d.get("ontology_name"),
            "description": (d.get("description") or [None])[0] if d.get("description") else None,
            "exact_synonyms": d.get("exact_synonyms", [])[:5],
            "broad_synonyms": d.get("broad_synonyms", [])[:3],
            "type": d.get("type"),
        })

    return {
        "query": query,
        "ontology_id": ontology_id,
        "numFound": num_found,
        "results": results,
    }


def main() -> None:
    """CLI entry point."""
    mcp.run()


if __name__ == "__main__":
    main()
