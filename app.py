import json
import os
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)

FACTCHECK_API_KEY = os.getenv("GOOGLE_FACTCHECK_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip()
OPENAI_API_URL = "https://api.openai.com/v1/responses"

TRUSTED_EVIDENCE_DOMAINS = [
    ".gov", ".gov.br", ".edu", ".edu.br", ".ac.", "who.int", "paho.org", "un.org",
    "scielo", "pubmed", "nih.gov", "ncbi.nlm.nih.gov", "doi.org", "nature.com",
    "science.org", "thelancet.com", "bmj.com", "cochranelibrary.com", "fiocruz.br",
    "ibge.gov.br", "ipea.gov.br", "planalto.gov.br", "senado.leg.br", "camara.leg.br",
    "bcb.gov.br", "anvisa.gov.br", "datasus.saude.gov.br", "saude.gov.br", "in.gov.br",
    "tse.jus.br", "stf.jus.br", "cnj.jus.br", "unesco.org", "worldbank.org", "oecd.org"
]

FACTCHECK_DOMAINS = [
    "aosfatos.org", "lupa.uol.com.br", "projetocomprova.com.br", "boatos.org", "e-farsas.com",
    "factcheck.org", "politifact.com", "snopes.com", "fullfact.org"
]

LOW_TRUST_PLATFORMS = [
    "facebook.com", "instagram.com", "tiktok.com", "x.com", "twitter.com", "whatsapp.com",
    "telegram.org", "youtube.com", "blogspot.com", "medium.com"
]

CLICKBAIT_WORDS = [
    "chocante", "urgente", "bomba", "você não vai acreditar", "escondem de você",
    "compartilhe antes que apaguem", "mídia não mostra", "cura milagrosa", "100% garantido",
    "proibido", "segredo revelado", "verdade que ninguém conta", "acabou de sair",
    "alerta máximo", "viralizou", "sem que você saiba", "não querem que você saiba"
]

ABSOLUTE_WORDS = [
    "sempre", "nunca", "todos", "ninguém", "nenhum", "com certeza", "definitivamente",
    "comprovado", "prova final", "garantido", "inquestionável", "indiscutível"
]

CLAIM_PATTERNS = [
    r"\b\d+[\.,]?\d*\s?(%|por cento|mil|milhão|milhões|bilhão|bilhões)\b",
    r"\b(causa|provoca|aumenta|reduz|cura|previne|mata|comprova|prova|garante|confirma|desmente)\b",
    r"\b(segundo|de acordo com|estudo|pesquisa|levantamento|relatório|dados|especialistas|cientistas)\b",
    r"\b(nunca|sempre|todos|ninguém|nenhum|exclusivo|confirmado|ilegal|obrigatório)\b",
    r"\b(ministério|governo|prefeitura|secretaria|universidade|hospital|oms|onu|ibge|anvisa|stf|tse)\b"
]

RATING_TRUE_WORDS = ["verdadeiro", "correto", "comprovado", "true", "accurate"]
RATING_FALSE_WORDS = ["falso", "fake", "enganoso", "mentira", "false", "mostly false", "pants", "misleading"]
RATING_MIXED_WORDS = ["impreciso", "parcial", "fora de contexto", "sem contexto", "exagerado", "mixed", "half true"]


class PageExtractionError(ValueError):
    pass


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("Informe um link para análise.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Link inválido. Use uma URL completa, por exemplo: https://exemplo.com/noticia")
    return url


def fetch_page(url: str) -> tuple[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; VerificadorVerdadeMVP/2.0; +https://example.local)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7"
    }
    resp = requests.get(url, headers=headers, timeout=14, allow_redirects=True)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type and content_type:
        raise PageExtractionError(
            f"O link retornou conteúdo do tipo '{content_type}', não uma página HTML comum."
        )
    return resp.text, resp.url


def clean_text_from_soup(soup: BeautifulSoup, limit: int = 30000) -> str:
    for tag in soup(["script", "style", "noscript", "svg", "form", "header", "footer", "nav", "aside"]):
        tag.decompose()
    paragraphs = []
    for el in soup.find_all(["h1", "h2", "h3", "p", "li", "blockquote"]):
        txt = " ".join(el.get_text(" ", strip=True).split())
        if len(txt) >= 40:
            paragraphs.append(txt)
    text = "\n".join(paragraphs)
    if not text:
        text = " ".join(soup.get_text(" ", strip=True).split())
    return text[:limit]


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "")
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 55]


def extract_claims(text: str) -> list[dict[str, Any]]:
    sentences = split_sentences(text)
    claims = []
    for sent in sentences:
        score = sum(1 for pattern in CLAIM_PATTERNS if re.search(pattern, sent, re.I))
        if score:
            claims.append({"text": sent[:500], "strength": score})
    if not claims:
        claims = [{"text": s[:500], "strength": 1} for s in sentences[:8]]
    claims = sorted(claims, key=lambda x: x["strength"], reverse=True)
    return claims[:12]


def extract_metadata(soup: BeautifulSoup) -> dict[str, str]:
    title = soup.title.string.strip() if soup.title and soup.title.string else "Sem título identificado"
    description = ""
    meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if meta_desc and meta_desc.get("content"):
        description = meta_desc["content"].strip()

    author = ""
    for selector in [
        {"name": "author"}, {"property": "article:author"}, {"name": "twitter:creator"},
        {"property": "og:site_name"}, {"name": "publisher"}
    ]:
        tag = soup.find("meta", attrs=selector)
        if tag and tag.get("content"):
            author = tag["content"].strip()
            break

    published = ""
    for selector in [
        {"property": "article:published_time"}, {"name": "date"}, {"name": "pubdate"},
        {"itemprop": "datePublished"}, {"property": "og:updated_time"},
        {"name": "DC.date.issued"}, {"name": "citation_publication_date"}
    ]:
        tag = soup.find("meta", attrs=selector)
        if tag and tag.get("content"):
            published = tag["content"].strip()
            break

    return {
        "title": title[:250],
        "description": description[:700],
        "author": author[:220],
        "published": published[:120]
    }


def extract_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    links = []
    for a in soup.find_all("a", href=True):
        href = urllib.parse.urljoin(base_url, a["href"])
        parsed = urllib.parse.urlparse(href)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            clean_href = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))
            links.append(clean_href)
    return list(dict.fromkeys(links))[:180]


def domain_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower().replace("www.", "")


def is_trusted_evidence(url: str) -> bool:
    d = domain_of(url)
    return any(token in d for token in TRUSTED_EVIDENCE_DOMAINS)


def is_factcheck_domain(url: str) -> bool:
    d = domain_of(url)
    return any(token in d for token in FACTCHECK_DOMAINS)


def is_low_trust_platform(url: str) -> bool:
    d = domain_of(url)
    return any(token in d for token in LOW_TRUST_PLATFORMS)


def extract_claimreview_jsonld(soup: BeautifulSoup) -> list[dict[str, str]]:
    reviews = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        queue = data if isinstance(data, list) else [data]
        idx = 0
        while idx < len(queue):
            item = queue[idx]
            idx += 1
            if isinstance(item, dict) and "@graph" in item and isinstance(item["@graph"], list):
                queue.extend(item["@graph"])
            item_type = item.get("@type") if isinstance(item, dict) else None
            types = item_type if isinstance(item_type, list) else [item_type]
            if isinstance(item, dict) and "ClaimReview" in types:
                rating = item.get("reviewRating", {}) if isinstance(item.get("reviewRating"), dict) else {}
                author_raw = item.get("author") or item.get("publisher") or {}
                author = author_raw.get("name", "") if isinstance(author_raw, dict) else str(author_raw)
                reviews.append({
                    "claim": str(item.get("claimReviewed", ""))[:500],
                    "rating": str(rating.get("alternateName") or rating.get("ratingValue") or "Avaliação encontrada")[:160],
                    "author": author[:180],
                    "url": str(item.get("url") or "")[:500]
                })
    return reviews[:10]


def rating_sentiment(rating: str) -> str:
    rating_l = (rating or "").lower()
    if any(w in rating_l for w in RATING_FALSE_WORDS):
        return "false"
    if any(w in rating_l for w in RATING_MIXED_WORDS):
        return "mixed"
    if any(w in rating_l for w in RATING_TRUE_WORDS):
        return "true"
    return "unknown"


def factcheck_api_search(query: str) -> list[dict[str, str]]:
    if not FACTCHECK_API_KEY or not query:
        return []
    try:
        url = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
        params = {"key": FACTCHECK_API_KEY, "query": query[:500], "pageSize": 8, "languageCode": "pt"}
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        results = []
        for claim in data.get("claims", []):
            for review in claim.get("claimReview", []):
                results.append({
                    "claim": claim.get("text", "")[:500],
                    "publisher": (review.get("publisher") or {}).get("name", "")[:180],
                    "rating": review.get("textualRating", "")[:160],
                    "url": review.get("url", "")[:500]
                })
        return results[:10]
    except Exception:
        return []


def fetch_evidence_snippets(links: list[str]) -> list[dict[str, str]]:
    evidence_links = [l for l in links if is_trusted_evidence(l) or is_factcheck_domain(l)]
    snippets = []
    for link in evidence_links[:5]:
        try:
            html, final_url = fetch_page(link)
            soup = BeautifulSoup(html, "html.parser")
            meta = extract_metadata(soup)
            text = clean_text_from_soup(soup, limit=2200)
            if text:
                snippets.append({
                    "url": final_url,
                    "domain": domain_of(final_url),
                    "title": meta.get("title", ""),
                    "text": text[:1800]
                })
        except Exception:
            continue
    return snippets


def count_unique_domains(links: list[str]) -> int:
    domains = {domain_of(l) for l in links if domain_of(l)}
    return len(domains)


def local_score_page(
    url: str,
    metadata: dict[str, str],
    text: str,
    links: list[str],
    claimreviews: list[dict[str, str]],
    api_reviews: list[dict[str, str]]
) -> tuple[int, list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    score = 45
    positives = []
    warnings = []
    details: dict[str, Any] = {}

    parsed = urllib.parse.urlparse(url)
    domain = domain_of(url)

    if parsed.scheme == "https":
        score += 5
        positives.append({"item": "A página usa HTTPS.", "weight": "+5"})
    else:
        score -= 8
        warnings.append({"item": "A página não usa HTTPS.", "weight": "-8"})

    if any(token in domain for token in TRUSTED_EVIDENCE_DOMAINS):
        score += 18
        positives.append({"item": "O domínio principal parece ser institucional, acadêmico ou oficial.", "weight": "+18"})
    elif any(token in domain for token in FACTCHECK_DOMAINS):
        score += 20
        positives.append({"item": "O domínio principal pertence a uma iniciativa de checagem factual conhecida.", "weight": "+20"})
    elif is_low_trust_platform(url):
        score -= 10
        warnings.append({"item": "O link é de plataforma social ou publicação aberta, exigindo verificação externa maior.", "weight": "-10"})

    if metadata.get("author"):
        score += 7
        positives.append({"item": f"Autor, veículo ou responsável editorial identificado: {metadata['author']}", "weight": "+7"})
    else:
        score -= 4
        warnings.append({"item": "Não foi possível identificar autor ou responsável editorial na página.", "weight": "-4"})

    if metadata.get("published"):
        score += 7
        positives.append({"item": f"Data de publicação/atualização encontrada: {metadata['published']}", "weight": "+7"})
    else:
        score -= 4
        warnings.append({"item": "Não foi possível localizar data de publicação ou atualização.", "weight": "-4"})

    text_len = len(text or "")
    details["text_length"] = text_len
    if text_len < 500:
        score -= 12
        warnings.append({"item": "O conteúdo textual extraído é muito curto, o que torna a análise frágil.", "weight": "-12"})
    elif text_len < 1500:
        score -= 5
        warnings.append({"item": "O conteúdo textual extraído é limitado; a checagem pode ficar incompleta.", "weight": "-5"})
    elif text_len < 8000:
        score += 5
        positives.append({"item": "Há texto suficiente para uma análise automatizada inicial.", "weight": "+5"})
    else:
        score += 7
        positives.append({"item": "Há volume textual amplo para leitura automatizada.", "weight": "+7"})

    trusted_links = [l for l in links if is_trusted_evidence(l)]
    factcheck_links = [l for l in links if is_factcheck_domain(l)]
    source_domains = count_unique_domains(links)
    details["trusted_links_count"] = len(trusted_links)
    details["factcheck_links_count"] = len(factcheck_links)
    details["source_domains_count"] = source_domains

    if len(trusted_links) >= 6:
        score += 16
        positives.append({"item": f"Encontradas {len(trusted_links)} referências oficiais, acadêmicas ou institucionais.", "weight": "+16"})
    elif len(trusted_links) >= 3:
        score += 10
        positives.append({"item": f"Encontradas {len(trusted_links)} referências oficiais, acadêmicas ou institucionais.", "weight": "+10"})
    elif len(trusted_links) >= 1:
        score += 5
        positives.append({"item": f"Encontrada(s) {len(trusted_links)} referência(s) oficial(is), acadêmica(s) ou institucional(is).", "weight": "+5"})
    else:
        score -= 8
        warnings.append({"item": "Não foram encontrados links claros para fontes oficiais, acadêmicas ou bases verificáveis.", "weight": "-8"})

    if factcheck_links:
        score += min(12, 4 + 3 * len(factcheck_links))
        positives.append({"item": "A página referencia iniciativas de checagem factual.", "weight": "+" + str(min(12, 4 + 3 * len(factcheck_links)))})

    if source_domains >= 8:
        score += 6
        positives.append({"item": "A página aponta para múltiplos domínios externos, favorecendo rastreabilidade.", "weight": "+6"})
    elif source_domains <= 1:
        score -= 4
        warnings.append({"item": "Há pouca diversidade de fontes externas detectadas.", "weight": "-4"})

    text_lower = (text or "").lower()
    clickbait_hits = [w for w in CLICKBAIT_WORDS if w in text_lower]
    details["clickbait_hits"] = clickbait_hits
    if clickbait_hits:
        dec = min(24, 6 + len(clickbait_hits) * 5)
        score -= dec
        warnings.append({"item": "Há termos típicos de sensacionalismo/clickbait: " + ", ".join(clickbait_hits[:6]), "weight": f"-{dec}"})

    absolute_hits = [w for w in ABSOLUTE_WORDS if re.search(r"\b" + re.escape(w) + r"\b", text_lower)]
    details["absolute_hits"] = absolute_hits
    if len(absolute_hits) >= 4:
        dec = min(12, 3 + len(absolute_hits))
        score -= dec
        warnings.append({"item": "O texto usa linguagem muito absoluta, o que exige cuidado interpretativo.", "weight": f"-{dec}"})

    claims = extract_claims(text)
    details["claims_count"] = len(claims)
    if not claims:
        score -= 5
        warnings.append({"item": "Poucas afirmações verificáveis foram detectadas automaticamente.", "weight": "-5"})
    elif len(claims) >= 6 and len(trusted_links) == 0 and not api_reviews:
        dec = min(14, 6 + len(claims) // 2)
        score -= dec
        warnings.append({"item": "Há várias afirmações verificáveis, mas poucas evidências externas fortes detectadas.", "weight": f"-{dec}"})

    all_reviews = claimreviews + api_reviews
    if all_reviews:
        true_count = sum(1 for r in all_reviews if rating_sentiment(r.get("rating", "")) == "true")
        false_count = sum(1 for r in all_reviews if rating_sentiment(r.get("rating", "")) == "false")
        mixed_count = sum(1 for r in all_reviews if rating_sentiment(r.get("rating", "")) == "mixed")
        if false_count:
            dec = min(35, 14 + false_count * 8)
            score -= dec
            warnings.append({"item": f"Checagens externas encontraram {false_count} avaliação(ões) falsa(s) ou enganosa(s) relacionada(s).", "weight": f"-{dec}"})
        if mixed_count:
            dec = min(18, 8 + mixed_count * 4)
            score -= dec
            warnings.append({"item": f"Checagens externas encontraram {mixed_count} avaliação(ões) parcial(is), imprecisa(s) ou fora de contexto.", "weight": f"-{dec}"})
        if true_count:
            inc = min(22, 10 + true_count * 5)
            score += inc
            positives.append({"item": f"Checagens externas encontraram {true_count} avaliação(ões) favorável(is) relacionada(s).", "weight": f"+{inc}"})
        if claimreviews:
            score += 5
            positives.append({"item": "A página contém marcação estruturada ClaimReview.", "weight": "+5"})

    score = max(0, min(100, int(round(score))))
    return score, positives[:10], warnings[:10], details


def classify(score: int) -> str:
    if score >= 85:
        return "Alta confiabilidade aparente"
    if score >= 70:
        return "Boa confiabilidade aparente"
    if score >= 55:
        return "Confiabilidade moderada"
    if score >= 40:
        return "Baixa verificabilidade ou resultado inconclusivo"
    return "Alto risco de desinformação ou baixa verificabilidade"


def truth_schema() -> dict[str, Any]:
    point_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claim": {"type": "string"},
            "reason": {"type": "string"}
        },
        "required": ["claim", "reason"]
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "classification": {"type": "string"},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
            "summary": {"type": "string"},
            "real_points": {"type": "array", "items": point_schema},
            "unverified_points": {"type": "array", "items": point_schema},
            "false_or_suspicious_points": {"type": "array", "items": point_schema},
            "recommendations": {"type": "array", "items": {"type": "string"}}
        },
        "required": [
            "score", "classification", "confidence", "summary", "real_points",
            "unverified_points", "false_or_suspicious_points", "recommendations"
        ]
    }


def extract_output_text_from_openai(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    texts: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if obj.get("type") in {"output_text", "text"} and isinstance(obj.get("text"), str):
                texts.append(obj["text"])
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data.get("output", []))
    return "\n".join(texts).strip()


def ai_analyze_page(
    final_url: str,
    metadata: dict[str, str],
    text: str,
    claims: list[dict[str, Any]],
    trusted_links: list[str],
    claimreviews: list[dict[str, str]],
    api_reviews: list[dict[str, str]],
    evidence_snippets: list[dict[str, str]],
    local_score: int
) -> tuple[dict[str, Any] | None, str | None]:
    if not OPENAI_API_KEY:
        return None, "OPENAI_API_KEY não configurada. A análise usou apenas heurística local."

    source_package = {
        "url": final_url,
        "domain": domain_of(final_url),
        "metadata": metadata,
        "local_score": local_score,
        "detected_claims": claims[:10],
        "trusted_links_detected": trusted_links[:15],
        "claimreview_on_page": claimreviews[:8],
        "external_factchecks": api_reviews[:8],
        "evidence_snippets_from_linked_sources": evidence_snippets[:5],
        "page_text_excerpt": (text or "")[:12000]
    }

    system_prompt = (
        "Você é um verificador factual e analista de confiabilidade editorial. "
        "Você deve avaliar apenas o conteúdo fornecido pelo sistema: página analisada, metadados, links, "
        "checagens externas e trechos de fontes vinculadas. Não invente dados, não diga que pesquisou na internet "
        "e não trate ausência de evidência como prova de falsidade. Quando não houver evidência suficiente, classifique "
        "como não verificado. Dê pontuação alta apenas quando houver autoria, rastreabilidade, fontes fortes e coerência factual. "
        "Dê pontuação baixa quando houver alegações graves sem evidência, linguagem sensacionalista, contradições, promessas absolutas "
        "ou checagens externas desfavoráveis. Responda sempre em português do Brasil."
    )

    user_prompt = (
        "Analise a confiabilidade factual da página abaixo e retorne JSON no esquema solicitado.\n\n"
        "Critérios obrigatórios:\n"
        "1. Identifique afirmações provavelmente reais/verificáveis quando houver fonte ou evidência suficiente.\n"
        "2. Identifique afirmações não verificadas quando o texto não traz fonte adequada.\n"
        "3. Identifique pontos falsos, suspeitos, exagerados ou fora de contexto quando houver sinais.\n"
        "4. A porcentagem deve variar conforme evidência, não use valor fixo.\n"
        "5. Seja conservador: IA não substitui checagem humana.\n\n"
        f"DADOS PARA ANÁLISE:\n{json.dumps(source_package, ensure_ascii=False)}"
    )

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "truth_analysis",
                "strict": True,
                "schema": truth_schema()
            }
        },
        "temperature": 0.2,
        "max_output_tokens": 1800
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post(OPENAI_API_URL, headers=headers, json=payload, timeout=35)
        if resp.status_code >= 400:
            return None, f"Erro na IA: {resp.status_code} — {resp.text[:500]}"
        data = resp.json()
        output_text = extract_output_text_from_openai(data)
        if not output_text:
            return None, "A IA não retornou texto estruturado."
        parsed = json.loads(output_text)
        parsed["score"] = max(0, min(100, int(parsed.get("score", local_score))))
        parsed["confidence"] = max(0, min(100, int(parsed.get("confidence", 50))))
        return parsed, None
    except Exception as exc:
        return None, f"Falha na análise de IA: {str(exc)[:500]}"


def combine_scores(local_score: int, ai_analysis: dict[str, Any] | None) -> int:
    if not ai_analysis:
        return local_score
    ai_score = int(ai_analysis.get("score", local_score))
    confidence = int(ai_analysis.get("confidence", 60))
    ai_weight = 0.65 + (min(100, max(0, confidence)) / 100) * 0.2
    local_weight = 1 - ai_weight
    return max(0, min(100, int(round(ai_score * ai_weight + local_score * local_weight))))


@app.get("/")
def home():
    return render_template("index.html")


@app.post("/api/check")
def check():
    try:
        input_url = request.json.get("url", "") if request.is_json else request.form.get("url", "")
        url = normalize_url(input_url)
        html, final_url = fetch_page(url)
        soup = BeautifulSoup(html, "html.parser")
        metadata = extract_metadata(soup)
        text = clean_text_from_soup(soup)
        claims = extract_claims(text)
        links = extract_links(soup, final_url)
        claimreviews = extract_claimreview_jsonld(soup)

        api_query = " ".join([metadata.get("title", ""), claims[0]["text"] if claims else ""]).strip()
        api_reviews = factcheck_api_search(api_query)
        local_score, positives, warnings, local_details = local_score_page(
            final_url, metadata, text, links, claimreviews, api_reviews
        )

        trusted_links = [l for l in links if is_trusted_evidence(l)]
        factcheck_links = [l for l in links if is_factcheck_domain(l)]
        evidence_snippets = fetch_evidence_snippets(links) if OPENAI_API_KEY else []
        ai_analysis, ai_error = ai_analyze_page(
            final_url, metadata, text, claims, trusted_links, claimreviews, api_reviews,
            evidence_snippets, local_score
        )

        final_score = combine_scores(local_score, ai_analysis)
        analysis_mode = "IA + heurística local" if ai_analysis else "Heurística local"
        classification = classify(final_score)
        if ai_analysis and ai_analysis.get("classification"):
            classification = f"{classification} — {ai_analysis['classification']}"

        response = {
            "url": final_url,
            "domain": domain_of(final_url),
            "score": final_score,
            "local_score": local_score,
            "ai_score": ai_analysis.get("score") if ai_analysis else None,
            "classification": classification,
            "analysis_mode": analysis_mode,
            "ai_enabled": bool(ai_analysis),
            "ai_error": ai_error,
            "metadata": metadata,
            "claims": claims,
            "positive_evidence": positives,
            "risk_points": warnings,
            "trusted_links": trusted_links[:12],
            "factcheck_links": factcheck_links[:12],
            "claimreview_on_page": claimreviews,
            "external_factchecks": api_reviews,
            "ai_analysis": ai_analysis,
            "local_details": local_details,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer": (
                "Este resultado é uma estimativa automatizada de confiabilidade, não uma decisão definitiva de verdade. "
                "Use como triagem inicial e confirme em fontes independentes."
            )
        }
        return jsonify(response)
    except requests.exceptions.RequestException as exc:
        return jsonify({
            "error": "Não consegui acessar o link. O site pode bloquear robôs, exigir login ou estar fora do ar.",
            "details": str(exc)[:300]
        }), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
