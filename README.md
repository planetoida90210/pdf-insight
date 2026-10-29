# PDF Insight

**Demo:** https://planetoida90210.github.io/pdf-insight/

![PDF Insight](docs/screenshot.png)

## Architektura

```
GitHub Pages (React + Vite)          DigitalOcean (FastAPI, Docker)               OpenRouter
pdf.js: walidacja, miniatury   →   POST /api/extract                          Claude Haiku 5.5
                                     pdfplumber + filtr ukrytego tekstu
                                     Tesseract OCR per strona
                               →   POST /api/analyze {extractionId}     →     structured output
Zod → widok, JSON, historia          walidacja Pydantic, 1 retry, grounding
```

- Dwa kroki API, bo UI pokazuje postęp (odczyt tekstu → analiza AI), a ponowienie powtarza tylko krok, który padł.
  Tekst zostaje na serwerze (cache 15 min); `/api/analyze` przyjmuje tylko id, więc nie da się go użyć jako
  darmowego proxy do LLM.
- Jeden schemat wyniku: Pydantic (backend) → `schema/analysis.schema.json`; Zod (frontend) waliduje odpowiedź przed
  wyświetleniem. Wspólne fixtures w `schema/fixtures/` testują oba walidatory.

## Decyzje

- **Ukryty tekst.** Testowy PDF ma na stronie 4 biały tekst na białym tle z instrukcją dla AI. Backend renderuje
  stronę i usuwa znaki, które nie są widoczne w pikselach (a nie „białe znaki”, bo brief ma biały tekst na ciemnym
  tle). Usunięty fragment trafia do ostrzeżeń, nie do modelu.
- **Prompt injection.** Treść dokumentu idzie do modelu jako dane w znaczniku z losowym id; system prompt zabrania
  wykonywania instrukcji z dokumentu; regex zgłasza podejrzane frazy; odpowiedź to wyłącznie JSON wg schematu.
- **Grounding.** Kwoty i daty, których nie ma w tekście źródłowym, są usuwane (z ostrzeżeniem).
- **OCR per strona.** Strona bez warstwy tekstowej → Tesseract `pol+eng`; przy niskiej pewności → odczyt przez model
  z obrazu.
- **Długie dokumenty.** Tekst > 40 000 znaków dzielony po stronach; wyniki fragmentów łączone, podsumowanie pisane
  z całości.
- **Bezpieczeństwo.** Klucz tylko w zmiennych DigitalOcean App Platform; CORS tylko dla domeny demo; limity: 10 MB, 200 stron,
  6 żądań/min na IP, dzienny limit wywołań LLM; brak `dangerouslySetInnerHTML`; logi bez treści dokumentów.
- **Rozważane i odrzucone:** Docling, PaddleOCR (wolne na współdzielonym CPU), LangChain + baza wektorowa (brak
  przypadku użycia), Redis do limitów (jedna replika wystarcza), tesseract.js w przeglądarce (wolny, duży bundle).

## Uruchomienie lokalne

Wymagania: Node 24, Python 3.12 + [uv](https://docs.astral.sh/uv/), Tesseract z językami `pol` i `eng`
(albo Docker).

```bash
# backend
cd backend
cp .env.example .env          # wpisz OPENROUTER_API_KEY
uv sync
uv run uvicorn app.main:app --reload --port 8000
# albo: docker build -t pdf-insight-api . && docker run --env-file .env -p 8000:8000 pdf-insight-api

# frontend (w katalogu głównym)
cp .env.example .env          # VITE_API_URL=http://localhost:8000
npm ci
npm run dev
```

Testy: `npm test`, `cd backend && uv run pytest`.

### Zmienne środowiskowe

| Zmienna              | Gdzie    | Opis                                                        |
| -------------------- | -------- | ----------------------------------------------------------- |
| `VITE_API_URL`       | frontend | adres backendu; bez niego `npm run build` kończy się błędem |
| `OPENROUTER_API_KEY` | backend  | klucz OpenRouter                                            |
| `LLM_MODEL`          | backend  | domyślnie `anthropic/claude-haiku-5.5`                      |
| `ALLOWED_ORIGINS`    | backend  | dozwolone originy CORS                                      |

Pozostałe limity (rozmiar, strony, OCR, rate limit) z wartościami domyślnymi: `backend/.env.example`.

## Znane ograniczenia

- Limity żądań i cache są w pamięci jednej repliki; restart je zeruje.
- OCR na współdzielonym CPU: skan wielostronicowy może przekroczyć 30 s.
- Grounding nie wychwyci zmyślonej kwoty, która przypadkiem występuje w tekście (np. „1”).
- Historia zapisuje tylko wyniki, nie pliki, więc po otwarciu z historii nie ma miniatur stron.
- Tekst dokumentu trafia do OpenRouter i dalej do dostawcy modelu.
- DigitalOcean podmienia odpowiedź 502 na własną stronę 504, więc „AI zwróciło niepoprawny wynik” widać jako
  „Analiza trwała zbyt długo”.
