# FinAgent Hub — Çok Ajanlı Portföy & RAG Karar Destek Sistemi

Portföy takibini yapay zekâ ajanlarıyla birleştiren bir fintech karar destek platformu. Seçilen hisseler için bilanço verilerini, resmi bildirimleri (SEC EDGAR / KAP), insider işlemlerini ve haberleri tarar; **kaynak atıflı, doğrulanmış** bir istihbarat raporu üretir.

**Yasal uyarı:** Uygulamanın çıktıları yapay zekâ tarafından kamuya açık verilerle, yalnızca bilgilendirme amacıyla üretilir. **Yatırım tavsiyesi değildir.**

## Ekran Görüntüleri
<img width="1903" height="949" alt="Ekran görüntüsü 2026-10-23 144135" src="https://github.com/user-attachments/assets/a485cf11-d48d-4ccc-9006-80f500ba9927" />
<img width="1907" height="950" alt="Ekran görüntüsü 2026-10-23 144523" src="https://github.com/user-attachments/assets/77a2449c-4b64-45b3-aa80-3e7e9071f3dc" />
<img width="1903" height="954" alt="Ekran görüntüsü 2026-10-23 144539" src="https://github.com/user-attachments/assets/6582324e-43bb-4a69-8ff7-4b621b9a5a1b" />
<img width="1902" height="299" alt="Ekran görüntüsü 2026-10-23 144549" src="https://github.com/user-attachments/assets/0e870629-e00a-45b2-b5d9-b90c70f12da4" />


## Özellikler

### Portföy & Risk
- **Çoklu para birimi:** TRY bazlı toplam değer, canlı USD/TRY kuru, hisse bazında yerel para birimi.
- **Fiyat ve kur etkisi ayrımı:** Açık K/Z, alış kuruyla (doğrulamalı giriş) hesaplanır ve fiyat kaynaklı / kur kaynaklı olarak ikiye ayrılır.
- **Pozisyon yönetimi:** Ekleme, ağırlıklı ortalama maliyetle birleştirme, düzenleme, satış (gerçekleşmiş K/Z) ve silme.
- **Yoğunlaşma analizi:** HHI ve efektif varlık sayısı (N_eff) ile portföy dağılım kalitesi, tek varlıkta yoğunlaşma uyarısı.
- **Piyasa bazlı beta:** BIST hisseleri için XU100, ABD hisseleri için S&P 500'e göre ampirik beta; yıllık volatilite, korelasyonlar ve 6 aylık normalize performans grafiği.

### Çok Ajanlı Analiz
Üç ajan çalışır; ilk ikisi paralel yürür:

1. **Ajan 1 — Bilanço, Tablolar & Tutarlılık:** Finansal tabloları ve rasyoları çeker, tutarlılık denetimi yapar, doğrulanmış faaliyet raporu varsa RAG ile kullanır.
2. **Ajan 2 — SEC EDGAR / KAP / Insider:** Resmi bildirimleri (10-Q, 8-K, KAP açıklamaları), Form 4 insider işlemlerini ve ağırlıklandırılmış haberleri toplar.
3. **Ajan 3 — Baş Strateji & Makro Sentez:** Önceki iki çıktıyı, tarihli ve rakamlı makro göstergeleri ve portföy bağlamını (ağırlık, yoğunlaşma) birleştirir; güçlü yönler, riskler, katalizörler ve "görüşü ne değiştirir?" bölümlerini üretir.

### Güvenilirlik Katmanı
LLM çıktısını doğrudan kullanıcıya göstermek yerine bir doğrulama katmanından geçirir:

- **Kaynak ağırlıklandırma:** Resmi kaynaklar (SEC EDGAR, şirket yatırımcı ilişkileri, finansal tablolar) 1,00; KAP düzenleyici bildirimleri 0,70; piyasa yorumu/blog kaynakları 0,25.
- **Atıf denetimi:** Kaynak listesinde olmayan (uydurma) atıflar filtrelenir.
- **Deterministik güven skoru:** LLM'in kendi beyanı yerine tablo bütünlüğü, doğrulanmış PDF varlığı ve resmi kaynak sayısı gibi bileşenlerden formülle hesaplanır.
- **PDF doğrulama:** Yüklenen belge, şirketin resmi faaliyet raporu / 10-K'sı değilse reddedilir; kişisel ya da alakasız PDF'ler vektör veritabanına girmez.
- **Birim ve tutarlılık kontrolleri:** Para birimi uyuşmazlığı, yüzdelik/oran birimi hataları ve çelişkili rasyolar için kural tabanlı denetimler.
- **Rapor geçmişi:** Her analiz tarihli ve versiyonlu saklanır, Markdown olarak indirilebilir.

## Tasarım Kararları
- **C# + Python ayrımı:** Ürün tarafı (portföy, K/Z, kullanıcı verisi) ASP.NET Core'da; yapay zekâ ekosistemi (ajanlar, RAG) Python/FastAPI'de. Ajan servisi ayrı olduğu için bağımsız ölçeklenip değiştirilebilir.
- **Paralel ajanlar:** Birbirinden bağımsız Ajan 1 ve Ajan 2 eş zamanlı çalışır; rapor süresi yaklaşık 77 sn'den 45–55 sn aralığına indi.
- **Hesaplamayı LLM'e bırakmama:** Rasyolar, ağırlıklar ve güven skoru kodda hesaplanır; LLM yalnızca yorumlar. Bu, yanlış birim ve uydurma sayı hatalarını azaltır.
- **Kaynak–iddia bağı:** Her iddia numaralı bir kaynağa bağlanır ve kaynak türüne göre ağırlıklandırılır.

## Teknoloji Yığını

| Katman | Teknoloji |
|---|---|
| Backend | C#, ASP.NET Core (.NET 8) |
| Ajan servisi | Python, FastAPI, Gemini API |
| RAG | NumPy & Yerel Vektör Deposu (Gemini Embeddings, Cosine Similarity)|
| Veri kaynakları | Yahoo Finance (yfinance), SEC EDGAR, KAP, finans haberleri |
| Frontend | React.js |

## Bilinen Sınırlamalar

Bunlar bilinçli olarak not edilmiş sınırlardır:

- **Holding ve finansal kuruluşlar:** Bankaları/finans şirketlerini konsolide eden holdinglerde (ör. KCHOL) Net Borç/FAVÖK ve işletme nakit akışı gibi sanayi rasyoları yanıltıcı olabilir. Sektöre duyarlı bir rasyo seti gerekir.
- **Veri kaynağı:** yfinance resmi bir API değildir; veriler gecikmeli veya tutarsız olabilir. Marjlar TTM/FY dönemi etiketlenmeden gösterilebilir.
- **Beta:** 6 aylık pencereyle hesaplanır, istatistiksel olarak gürültülüdür.
- **Insider verisi:** Form 4 işlem kodları (açık piyasa satışı, vergi kesintisi, opsiyon kullanımı) ayrıştırılmaz; kurumsal pozisyon haberleri insider işlemiyle ayrı değerlendirilmez.
- **Kota:** Gemini API kotası dolduğunda analiz ve PDF yükleme başarısız olur.
- **Doğrulama:** Kural tabanlı denetimler kapsamlı ama kusursuz değildir; çıktılar bağımsız olarak kontrol edilmelidir.

## Geliştirici

**Emir İşbakan** — [GitHub](https://github.com/Emir-bit-ux)
