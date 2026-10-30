# AI_LOG

## Narzędzia

- **Claude Code** w agentowym IDE bb. Model dobieram do kontekstu i złożoności zadania: tańszy do prostych,
  mechanicznych kroków, **Claude Opus 5.5** (najwyższy poziom rozumowania) do planu, architektury, review
  i trudnych błędów. Wątek-orkiestrator planował i scalał pracę, a równoległe wątki robiły backend, frontend,
  review, audyt bezpieczeństwa i testy na 85 złośliwych PDF-ach, każdy w osobnym git worktree.
- W samej aplikacji ta sama zasada: analiza PDF-a to wąskie zadanie (ekstrakcja do schematu), więc idzie do
  Claude Haiku 5.5 przez OpenRouter, który jest szybki i tani.
- **Greptile**: automatyczny review każdego PR, uwagi poprawione przed merge.
- Poza AI: GitHub CLI, Docker, pytest, Vitest.

## Kluczowe prompty

1. „Przeanalizuj brief i testowy PDF jak dane od przeciwnika: warstwa tekstowa kontra render (niewidoczny tekst,
   prompt injection), strony bez warstwy tekstowej, formaty liczb, dat i walut. Dla każdej pułapki podaj, jak ją
   wykryć, obsłużyć i zweryfikować. Plan ma pokryć F-01–F-10 1:1, łącznie z OCR.”
   → filtr niewidocznego tekstu na podstawie wyrenderowanych pikseli (s. 4) i decyzja o OCR osobno dla każdej
   strony (s. 11).
2. „Oceń ten stack pod kątem DoD z briefu: wynik < 30 s, demo żyje 14 dni, każdą linię kodu muszę obronić.
   Dla PaddleOCR, Docling, LangChain i bazy wektorowej: jaki konkretny problem rozwiązują w tym zakresie
   i ile kosztują w latencji, złożoności i powierzchni ataku. Zostaw tylko to, co ma uzasadnienie.”
   → wszystkie cztery wypadły: brak przypadku użycia dla retrievalu, wolny OCR na współdzielonym CPU.
   Redis i IndexedDB zastąpiły limity w pamięci (jedna replika) i localStorage.
3. „Zbuduj F-01–F-10 jako orkiestrator. Jedno źródło prawdy: PLAN.md z kontraktem API, schematem i zasadami.
   Backend i frontend robią osobni agenci w osobnych git worktree, a wspólne fixture'y muszą przejść
   i Pydantic, i Zod. Małe commity w Conventional Commits, zero martwego kodu, każdy krok sprawdzony komendą,
   nie deklaracją.”
   → równoległa praca bez konfliktów; test w CI wykrywa rozjazd schematów backendu i frontendu.
4. „Zaatakuj aplikację jak recenzent, który chce ją złamać. Zbuduj korpus złośliwych PDF-ów (RTL, zdjęcia
   z telefonu, obrócone i przycięte strony, fałszywe warstwy tekstu, bomby, injection) i uruchom go na produkcji.
   Dla każdego błędu: plik, wymaganie z briefu, przyczyna w kodzie (plik:linia), najmniejsza uniwersalna poprawka.
   Żadnych heurystyk dopasowanych do przykładowych plików.”
   → 85 plików, raport z 23 błędami, poprawki w PR #4–#11.
5. „Każda strona ma zostać przeczytana: bez limitu stron i bez obcinania tekstu, na obecnym hostingu
   (1 współdzielony vCPU), bez dodatkowych kosztów, w DoD < 30 s. Regresji nie przyjmuję: każdą zmianę mierz
   przed i po na tym samym korpusie.”
   → OCR skanów w przeglądarce (tesseract.js, równoległe workery), serwer tylko weryfikuje.
   Skan 30 stron: 76 s → 19 s.

## Gdzie AI się pomyliło i jak to poprawiłem

| Błąd AI                                                                                                                                                                                | Jak wyszło na jaw                                                                                                                             | Poprawka                                                                                                                     |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Licznik zdań streszczenia na regexach z listą polskich skrótów (`sp. z o.o.`, `r.`, `ul.`)                                                                                             | Na produkcji odrzucał poprawne streszczenia: nawias po `S.A.` w umowie, `Inc.` i `Sp. k.` w angielskiej fakturze → `AI_INVALID_RESPONSE`      | Model zwraca `summarySentences` jako listę, schemat wymusza 3–5 elementów, licznik usunięty (#2, #3)                         |
| Weryfikacja dat w źródle przez tabele nazw miesięcy PL/EN                                                                                                                              | Prawdziwe daty `Sep 29, 2026`, `29. September 2026`, francuskie i hiszpańskie usuwane jako zmyślone                                           | Data zostaje, gdy w tekście są cyfry jej roku i dnia, w dowolnym języku (#3)                                                 |
| Limity `MAX_OCR_PAGES` i `TEXT_LIMIT`: strony ponad limit pomijane, żeby zmieścić się w czasie na 1 vCPU                                                                               | Odrzuciłem: brief wymaga analizy dokumentu, nie jego początku. Korpus potwierdził, że fakty ze s. 100 i 190 ginęły                            | OCR skanów w przeglądarce, każda strona czytana; zbyt długi tekst → jawny błąd `TEXT_TOO_LONG` zamiast cichego obcięcia (#4) |
| Polskie fragmenty w prompcie (znacznik `[Strona N]`, kody typów, przykład `184 500,00 zł`)                                                                                             | Streszczenia po polsku dla dokumentów hebrajskich i chińskich, potem polskie słowa wewnątrz hebrajskich zdań                                  | Neutralne znaczniki stron; walidacja pisma słów streszczenia, przy niezgodności 1 ponowienie z listą obcych słów (#5, #9)    |
| Po przejściu ekstrakcji na pdfium minusy uznane za niewidoczny tekst                                                                                                                   | Faktura z ujemnymi pozycjami: `-604,62 USD` trafiało do analizy jako kwota dodatnia. Box minusa to sama kreska (~1 px), wycinek bez kontrastu | Wycinek do oceny widoczności min. 4 px; test, który bez poprawki pada (#11)                                                  |
| Vision dla 4 najmniej pewnych stron każdego skanu, także czystego                                                                                                                      | Pomiar na produkcji: skan 10 stron 27,6 s, 30 stron 43,6 s, łamie DoD < 30 s                                                                  | Nowa miara pewności strony (odsetek słów pewnych ≥ 90); vision tylko poniżej progu. Czyste skany: 0 wywołań (#10)            |
| Prompt kazał zgłaszać każdy tekst, który „próbuje instruować”                                                                                                                          | „SPRAWDŹ NUMER RACHUNKU” na fakturze pro forma oznaczone jako prompt injection                                                                | Zgłaszane tylko instrukcje skierowane do modelu; polecenia dla czytelnika to zwykła treść (#15)                              |
| Dwa równoległe `/api/analyze` z jednym id → dwie płatne analizy; zabity worker zostawiał działający Tesseract                                                                          | Review Greptile                                                                                                                               | Id rezerwowane przed pierwszym `await`; kill całej grupy procesów; testy, które bez poprawek padają (#1)                     |
| Drobniejsze: TypeScript 7 (typescript-eslint wymaga < 6.1), „biały tekst = ukryty” (brief ma biały tekst na ciemnym tle), IP klienta z pierwszego hopu `X-Forwarded-For` (podrabialny) | Sprawdzenie zależności, test na PDF-ie briefu, review bezpieczeństwa                                                                          | TS 6.0.3, widoczność oceniana z pikseli renderu, nagłówek `do-connecting-ip` od DigitalOcean                                 |
