import os
import json
import numpy as np
from pypdf import PdfReader
from google import genai

STORAGE_DIR = "vector_store"
os.makedirs(STORAGE_DIR, exist_ok=True)

FINANCIAL_KEYWORDS = [
    "faaliyet raporu", "bilanço", "gelir tablosu", "nakit akış", "özsermaye",
    "finansal tablolar", "bağımsız denetim", "hasılat", "favök", "ebitda",
    "annual report", "10-k", "10-q", "balance sheet", "income statement", "cash flows"
]

def validate_financial_pdf(full_text: str, ticker: str, company_name: str, total_chunks: int) -> tuple[bool, str]:
    """
    Yüklenen PDF'in gerçekten bir finansal rapor / faaliyet raporu olup olmadığını
    ve ilgili şirkete ait olup olmadığını doğrular. (Öğrenci belgesi vb. dosyaları reddeder).
    """
    text_low = full_text.lower()
    clean_ticker = ticker.upper().replace(".IS", "").lower()

    # 1. Kişisel/Alakasız belge tespiti
    if "öğrenci belgesi" in text_low or "transkript" in text_low or "yükseköğretim" in text_low:
        return (False, "Reddedildi: Yüklenen dosya bir öğrenci/okul belgesidir, finansal faaliyet raporu değildir.")

    # 2. Finansal anahtar kelime kontrolü
    matched_kw = [kw for kw in FINANCIAL_KEYWORDS if kw in text_low]
    if len(matched_kw) < 2:
        return (False, "Reddedildi: Belgede yeterli finansal tablo veya faaliyet raporu terminolojisi bulunamadı.")

    # 3. Minimum chunk eşiği
    if total_chunks < 3:
        return (False, f"Uyarı/Red: Belge çok kısa ({total_chunks} chunk). Bir faaliyet raporu en az 3+ metin parçası içermelidir.")

    # 4. Şirket / Sembol eşleşmesi kontrolü
    comp_first_word = (company_name or "").split()[0].lower() if company_name else ""
    has_entity_match = (clean_ticker in text_low) or (comp_first_word and len(comp_first_word) > 2 and comp_first_word in text_low)

    if not has_entity_match:
        return (False, f"Reddedildi: Yüklenen PDF içerisinde '{ticker.upper()}' sembolü veya şirket adı geçmemektedir.")

    return (True, f"Doğrulandı: {len(matched_kw)} finansal terim ve şirket eşleşmesi bulundu.")

def score_chunk_financial_density(text: str) -> float:
    """Metin parçasının finansal tablo, rakam ve stratejik anahtar kelime yoğunluğunu puanlar."""
    t_low = text.lower()
    score = 0.0
    high_value_terms = [
        "revenue", "operating income", "net income", "gross margin", "cash flow",
        "balance sheet", "total assets", "total debt", "blackwell", "rubin", "data center",
        "risk factors", "export control", "hasılat", "bilanço", "net kar", "favök",
        "faaliyet karı", "nakit akış", "özsermaye", "borç", "yatırım"
    ]
    for term in high_value_terms:
        if term in t_low:
            score += 3.0
    # Sayı, yüzde ve para birimi sembol yoğunluğu
    digit_count = sum(c.isdigit() for c in text)
    symbol_count = sum(text.count(s) for s in ["$", "%", "₺", "€", "billion", "million", "milyar", "milyon"])
    score += (digit_count / 40.0) + (symbol_count * 1.5)
    return score


def extract_and_chunk_pdf(file_path: str, chunk_size: int = 2200, overlap: int = 250) -> dict:
    reader = PdfReader(file_path)
    total_pages = len(reader.pages)
    total_chars = 0
    empty_pages = 0
    chunks = []
    full_text_parts = []
    
    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = " ".join(text.split())
        char_len = len(text)
        total_chars += char_len
        
        if char_len < 50:
            empty_pages += 1
            continue
            
        full_text_parts.append(text)
        step = max(chunk_size - overlap, 400)
        for i in range(0, char_len, step):
            chunk_text = text[i:i + chunk_size]
            if len(chunk_text) >= 120:
                chunks.append({
                    "page": page_num,
                    "char_len": len(chunk_text),
                    "fin_score": score_chunk_financial_density(chunk_text),
                    "text": chunk_text
                })

    full_text = " ".join(full_text_parts)
    stats = {
        "totalPages": total_pages,
        "emptyOrScannedPages": empty_pages,
        "totalExtractedChars": total_chars,
        "chunkSize": chunk_size,
        "overlap": overlap,
        "totalChunksGenerated": len(chunks),
        "isLikelyScanned": (total_chars / max(total_pages, 1)) < 100
    }
    return {"chunks": chunks, "stats": stats, "full_text": full_text}

def ingest_pdf_to_vector_store(client: genai.Client, ticker: str, company_name: str, file_path: str, filename: str) -> dict:
    parsed = extract_and_chunk_pdf(file_path)
    chunks = parsed["chunks"]
    stats = parsed["stats"]
    full_text = parsed["full_text"]

    if not chunks:
        raise ValueError("PDF'ten metin çıkarılamadı (Taranmış görsel PDF olabilir).")

    # Belge Doğrulaması
    is_valid, validation_msg = validate_financial_pdf(full_text, ticker, company_name, len(chunks))
    if not is_valid:
        raise ValueError(validation_msg)

    # Gemini Free Tier 100 istek/dakika limitine (429 RESOURCE_EXHAUSTED) takılmamak için:
    # Tüm PDF içerisindeki finansal yoğunluğu en yüksek 85 parçayı seç ve sayfa sırasına göre diz!
    if len(chunks) > 85:
        top_chunks = sorted(chunks, key=lambda x: x["fin_score"], reverse=True)[:85]
        chunks_to_embed = sorted(top_chunks, key=lambda x: x["page"])
    else:
        chunks_to_embed = chunks

    texts = [c["text"] for c in chunks_to_embed]

    # Tek seferde (<= 85 < 100 limit) gönder
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=texts
    )

    records = []
    for i, emb in enumerate(response.embeddings):
        records.append({
            "page": chunks_to_embed[i]["page"],
            "source_file": filename,
            "text": chunks_to_embed[i]["text"],
            "vector": emb.values
        })

    clean_ticker = ticker.upper().replace(".IS", "")
    store_path = os.path.join(STORAGE_DIR, f"{clean_ticker}_vectors.json")
    
    payload = {
        "fileName": filename,
        "isVerifiedFinancialDoc": True,
        "validationNote": validation_msg,
        "stats": stats,
        "records": records
    }
    with open(store_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    stats["totalChunksGenerated"] = len(records)
    return {**stats, "validationNote": validation_msg}

def clear_rag_store(ticker: str) -> bool:
    """Hatalı yüklenmiş PDF vektörlerini (örn. Ogrenci_Belgesi.pdf) temizler."""
    clean_ticker = ticker.upper().replace(".IS", "")
    store_path = os.path.join(STORAGE_DIR, f"{clean_ticker}_vectors.json")
    if os.path.exists(store_path):
        os.remove(store_path)
        return True
    return False

def get_rag_status(ticker: str) -> dict:
    clean_ticker = ticker.upper().replace(".IS", "")
    store_path = os.path.join(STORAGE_DIR, f"{clean_ticker}_vectors.json")
    if not os.path.exists(store_path):
        return {"hasRag": False, "isVerified": False, "chunks": 0, "fileName": None, "warning": None}
    try:
        with open(store_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Eski doğrulanmamış (Ogrenci_Belgesi vb.) formatta kalmışsa otomatik geçersiz say ve sil!
        if isinstance(data, list) or not data.get("isVerifiedFinancialDoc", False):
            os.remove(store_path)
            return {
                "hasRag": False,
                "isVerified": False,
                "chunks": 0,
                "fileName": None,
                "warning": "Doğrulanmamış eski PDF (Öğrenci belgesi vb.) sistemden otomatik temizlendi."
            }

        records = data.get("records", [])
        return {
            "hasRag": len(records) >= 3,
            "isVerified": True,
            "chunks": len(records),
            "fileName": data.get("fileName"),
            "warning": None
        }
    except Exception:
        return {"hasRag": False, "isVerified": False, "chunks": 0, "fileName": None, "warning": None}

def search_company_documents(client: genai.Client, ticker: str, query: str, top_k: int = 5) -> list[dict]:
    st = get_rag_status(ticker)
    if not st["hasRag"] or not st["isVerified"]:
        return []

    clean_ticker = ticker.upper().replace(".IS", "")
    store_path = os.path.join(STORAGE_DIR, f"{clean_ticker}_vectors.json")
    with open(store_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = data.get("records", [])
    q_resp = client.models.embed_content(model="gemini-embedding-001", contents=query)
    q_vec = np.array(q_resp.embeddings[0].values)

    scored = []
    for rec in records:
        doc_vec = np.array(rec["vector"])
        sim = np.dot(q_vec, doc_vec) / (np.linalg.norm(q_vec) * np.linalg.norm(doc_vec))
        scored.append({
            "score": round(float(sim), 3),
            "page": rec["page"],
            "source_file": rec["source_file"],
            "text": rec["text"]
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
