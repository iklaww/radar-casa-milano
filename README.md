# Radar Casa Milano

Una dashboard personale degli annunci di case in vendita a Milano. Ogni mattina raccoglie i nuovi annunci da più fonti, tiene lo storico dei prezzi e dà a ogni annuncio un **punteggio "affare" da 0 a 100**. Gli avvisi arrivano su **Telegram**.

Gira gratis su GitHub: non serve un server né un computer acceso.

- **Dashboard**: la apri dal telefono o dal computer. Puoi sfogliare tutti i quartieri e vedere la mappa, il €/m² mediano, l'andamento dei prezzi, le occasioni e lo storico di ogni annuncio.
- **Telegram**: ricevi un avviso quando esce una nuova occasione o quando un annuncio cala di prezzo, più un riepilogo ogni mattina.

---

## Come funziona

```
 Idealista (API) ─┐
 Email di avviso ─┼─► raccolta ─► database con storico prezzi ─► punteggio ─► dashboard (GitHub Pages)
 (Immobiliare,    │                                                        └─► Telegram
  Casa.it, …)     │
 CSV (aste…) ─────┘
```

Il **punteggio** somma cinque elementi:

| Elemento | Punti | Cosa misura |
|---|---|---|
| Prezzo vs quartiere | 45 | €/m² rispetto alla mediana degli annunci simili nello stesso quartiere |
| Vs quotazioni OMI | 15 | €/m² rispetto ai valori ufficiali dell'Agenzia delle Entrate (se li carichi) |
| Ribassi | 20 | Quanto è sceso il prezzo dal massimo |
| Tempo sul mercato | 10 | Dopo 1-5 mesi online c'è più margine di trattativa |
| Venditore motivato | 10 | Parole come "urgente", "trattabile", "trasferimento" |

Alcuni prezzi bassi non sono veri affari. Per "nuda proprietà", "occupato", "affittato" e simili il punteggio viene ridotto e compare un avviso. Per gli immobili "da ristrutturare" lo sconto normale dovuto ai lavori (circa 15%) viene tolto dal calcolo. Lo stesso immobile pubblicato su più portali viene riconosciuto e mostrato una volta sola.

---

## Installazione (circa 30 minuti, una volta sola)

### 1. Crea il repository su GitHub
1. Crea un account gratuito su [github.com](https://github.com).
2. Clicca **New repository**, chiamalo `radar-casa-milano` e scegli **Public**. GitHub Pages gratuito richiede un repository pubblico: vengono pubblicati solo i dati degli annunci, mai le tue password.
3. Clicca **uploading an existing file** e trascina dentro **tutti** i file e le cartelle di questo progetto.
   La cartella `.github` è nascosta su Mac e Windows. Se non viene caricata, crea il file a mano: **Add file → Create new file**, scrivi come nome `.github/workflows/radar.yml` e incolla il contenuto del file. Fai lo stesso per `test-telegram.yml`.

### 2. Attiva la dashboard
**Settings → Pages →** Source: *Deploy from a branch*, Branch: `main`, cartella `/docs` → **Save**.
Dopo un minuto la dashboard è online su `https://TUO-UTENTE.github.io/radar-casa-milano/`. All'inizio mostra dati di esempio.
Copia questo indirizzo in `config.toml` alla voce `dashboard_url`.

### 3. Crea il bot Telegram
1. Su Telegram apri **@BotFather**, scrivi `/newbot` e scegli un nome. Ricevi un **token**, una stringa del tipo `123456:ABC-...`.
2. Apri il tuo nuovo bot e mandagli un messaggio qualsiasi, per esempio "ciao".
3. Nel browser apri `https://api.telegram.org/botIL_TUO_TOKEN/getUpdates` e cerca `"chat":{"id":123456789`. Quel numero è il tuo **chat id**.

### 4. Inserisci le chiavi segrete
Nel repository: **Settings → Secrets and variables → Actions → New repository secret**. Aggiungi:

| Nome | Valore | Obbligatorio |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | il token del punto 3 | sì |
| `TELEGRAM_CHAT_ID` | il chat id del punto 3 | sì |
| `IDEALISTA_API_KEY` / `IDEALISTA_API_SECRET` | chiavi API Idealista (punto 5) | consigliato |
| `EMAIL_USER` / `EMAIL_PASSWORD` | casella che riceve gli avvisi (punto 6) | consigliato |
| `EMAIL_IMAP_HOST` | solo se non usi Gmail (es. `imap.libero.it`) | no |

Poi vai su **Actions → Prova notifiche Telegram → Run workflow**: in pochi secondi deve arrivarti un messaggio.

### 5. Fonte 1: API ufficiale di Idealista
Chiedi l'accesso su <https://developers.idealista.com/access-request>, spiegando che è un uso personale e non commerciale. La risposta può richiedere qualche giorno e l'accesso non è garantito. Il piano gratuito ha un limite mensile di richieste: per questo `pagine_per_giorno = 3` in `config.toml`. Se il tuo limite è diverso, cambia il valore.

### 6. Fonte 2: email di avviso dei portali (Immobiliare.it, Casa.it, Idealista, …)
È il modo pulito per avere anche Immobiliare.it e Casa.it.
1. Crea una casella **Gmail dedicata** (per esempio `radarcasa.tuonome@gmail.com`). Attiva la verifica in due passaggi e crea una **password per le app** (Account Google → Sicurezza → Password per le app). Questa password va in `EMAIL_PASSWORD`.
2. Su Immobiliare.it, Casa.it, Idealista, Wikicasa e gli altri portali, **salva le ricerche** per Milano (o per i quartieri che ti interessano) e attiva gli avvisi email **immediati o giornalieri** verso quella casella.
3. Ogni mattina il programma legge gli avvisi arrivati e ne estrae prezzo, metri quadri, locali e indirizzo. La posizione sulla mappa viene trovata con OpenStreetMap.

Più ricerche salvi, più annunci entrano nel radar. Puoi creare per esempio una ricerca per municipio.

### 7. Quartieri (consigliato)
Scarica i confini dei quartieri (**NIL – Nuclei d'Identità Locale**) dal portale open data del Comune di Milano, <https://dati.comune.milano.it>: cerca "NIL" e scarica il formato **GeoJSON**. Rinomina il file `quartieri.geojson` e caricalo nella cartella `data/`.
Se nel file il nome del quartiere non si chiama `NIL`, cambia `campo_nome_quartiere` in `config.toml`.
Senza questo file vengono usati i quartieri indicati dai portali, che sono meno uniformi.

### 8. Quotazioni OMI (facoltativo)
Dal sito dell'Agenzia delle Entrate (servizio *Forniture dati OMI*, accesso con SPID) scarica per il comune di Milano:
- il file `..._VALORI.csv` delle quotazioni;
- il file **KML delle zone OMI** di Milano (da GEOPOI).

Caricali entrambi in `data/omi/`. Il punteggio userà anche il confronto con i valori ufficiali.

### 9. Fonte 3: aste e annunci trovati altrove
Copia `data/import/esempio_aste.csv`, rinominalo (per esempio `aste.csv`) e aggiungi una riga per ogni immobile. Va bene per le aste del Portale Vendite Pubbliche, le agenzie o il passaparola. Le colonne sono descritte in `radar/sources/csv_import.py`.

### 10. Primo avvio
**Actions → Radar casa Milano → Run workflow**. Dopo qualche minuto la dashboard mostra i dati veri al posto di quelli di esempio. Da lì in poi il programma parte da solo ogni mattina.

---

## Personalizzare (`config.toml`)
Il file si modifica direttamente su GitHub con l'icona della matita.
- `[ricerca]`: budget e metratura. Gli annunci fuori range non vengono salvati.
- `[telegram]`:
  - `soglia_nuovi` (es. 70): punteggio minimo per ricevere l'avviso di un nuovo annuncio;
  - `soglia_ribasso_pct`: ribasso minimo per essere avvisato;
  - `quartieri`: per limitare gli avvisi ad alcune zone;
  - `preferiti`: annunci da seguire sempre. Il codice lo trovi nel dettaglio dell'annuncio in dashboard, col pulsante **Copia**.
- `[punteggio]`: le parole chiave che alzano o abbassano il punteggio.

## Buono a sapersi
- **Il primo mese** il punteggio "tempo sul mercato" e lo storico dei ribassi sono poveri, perché il radar conosce solo gli annunci visti da quando è partito. Il valore cresce con i mesi.
- Il punteggio si basa sui **prezzi richiesti**, non su quelli di vendita: a Milano lo scarto in trattativa è spesso del 5-10%. La "prima proposta indicativa" è solo un punto di partenza.
- La stella ★ dei preferiti nella dashboard resta salvata nel browser che stai usando. Per gli avvisi Telegram usa `preferiti` in `config.toml`.
- Se GitHub ti scrive che il workflow programmato è stato disattivato per inattività, riattivalo da **Actions** con un clic.
- Per provare la dashboard in locale: `python -m radar demo`, poi `cd docs && python -m http.server` e apri <http://localhost:8000>.
- Rispetta i termini d'uso dei portali. Questo progetto usa solo l'API ufficiale di Idealista e le email di avviso che ricevi tu: non fa scraping dei siti.
