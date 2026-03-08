# Telegram -> MetaTrader Bot

Bot Python con pannello web locale che:

- ascolta un canale Telegram tramite `Telethon`
- riconosce messaggi di apertura trade, TP, SL e break even
- apre e gestisce le operazioni su MetaTrader
- espone una control room web per configurazione, log live e stato segnali

## Interfaccia

`main.py` avvia una UI web locale su `http://127.0.0.1:8765`.

La dashboard include:

- configurazione Telegram
- configurazione MetaTrader
- parametri di trading
- salvataggio config via browser
- avvio e stop del bot
- test MetaTrader
- autorizzazione Telegram in due step
- log live con polling
- board degli ultimi segnali

## Messaggi supportati

- apertura trade
- `Stop Loss preso`
- `Take Profit 1/2/3 preso`
- `TP1`, `TP2`, `TP3`, `TAKE PROFIT 1/2/3`
- `Take Profit preso`
- `Sposto lo Stop Loss a: Break Even`
- `Chiusa a Break Even`
- `Chiusa in take profit`

## Comportamento

- all'apertura del segnale apre un'operazione separata per ogni TP disponibile (`TP1`, `TP2`, `TP3`, ...)
- in modalita' `auto` decide se aprire a mercato o come pending in base a `Entry`
- ogni operazione viene associata al suo TP dedicato anche su broker, se abilitato
- quando arriva `TP1`, `TP2` o `TP3` chiude solo l'operazione assegnata a quel livello
- quando arriva il messaggio di break even sposta lo SL al prezzo di ingresso per tutte le operazioni ancora aperte del segnale
- quando arriva una chiusura finale prova a chiudere o cancellare il residuo

## Struttura

- `main.py`: avvio server web locale
- `telegram_mt5_bot/parser.py`: parser dei messaggi
- `telegram_mt5_bot/telegram_listener.py`: listener Telegram con Telethon
- `telegram_mt5_bot/mt5_bridge.py`: integrazione MetaTrader
- `telegram_mt5_bot/processor.py`: logica di gestione segnali
- `telegram_mt5_bot/web/app.py`: app Flask
- `telegram_mt5_bot/web/controller.py`: orchestration backend della dashboard
- `telegram_mt5_bot/web/templates/`: template HTML
- `telegram_mt5_bot/web/static/`: CSS e JavaScript della dashboard
- `config.json`: file generato dal pannello
- `runtime_state.json`: stato locale dei segnali attivi

## Requisiti

- Python 3.11+ consigliato
- `Flask`
- `telethon`
- credenziali Telegram `api_id` e `api_hash` da `my.telegram.org`
- terminale MetaTrader aperto sulla stessa macchina del bot

### Nota MetaTrader su Linux

Il package Python ufficiale `MetaTrader5` normalmente e' disponibile su Windows. Per questo in `requirements.txt` viene installato solo su Windows.

Su Linux hai due strade pratiche:

- usare un bridge compatibile con MT5 via Wine
- eseguire il bot su Windows insieme al terminale MT5

Il pannello web e la parte Telegram funzionano anche senza il package `MetaTrader5`, ma il bridge trading non potra' eseguire ordini finche' quel layer non viene risolto.

Per MT4 non esiste in questo progetto un bridge Python ufficiale equivalente: serve un bridge dedicato, tipicamente con EA MQL4.

## Installazione

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Avvio

```bash
python main.py
```

Poi apri:

```text
http://127.0.0.1:8765
```

Variabili opzionali:

- `BOT_WEB_HOST`
- `BOT_WEB_PORT`

## Configurazione dalla dashboard

### Telegram

- `API ID`
- `API Hash`
- `Session Name`
- `Phone Number`
- `Source Chat`

Flusso autorizzazione:

1. salva la config
2. clicca `Invia codice`
3. inserisci codice Telegram
4. se richiesto, inserisci la password 2FA
5. conferma l'autorizzazione

### MetaTrader

- `Platform` (`mt4` o `mt5`)
- `Terminal Path`
- `Login`, `Password`, `Server`
- `Portable Mode`
- `Magic`
- `Comment Prefix`
- `Deviation Points`

### Trading

- `Default Volume`
- `Execution Mode`
- `Max Market Deviation`
- `Allow Pending Orders`
- `Prevent Duplicate Symbol`
- `Apply Selected TP To Broker`
- `Symbol Map`
- `Allowed Symbols`

## Logica di associazione dei messaggi

Molti messaggi del canale non hanno un ID trade. Il bot usa questa strategia:

- se nel messaggio c'e' il simbolo, aggiorna l'ultimo segnale attivo di quel simbolo
- se il messaggio non contiene simbolo, aggiorna l'ultimo segnale attivo in assoluto

Questo copre bene i casi mostrati nel tuo esempio, ma se nel canale ci sono piu' trade contemporanei senza simbolo esplicito, l'associazione puo' essere ambigua.

## Test

```bash
python -m unittest discover -s tests -v
```

## Note

- il pannello e' web, non desktop
- il bot usa `Telethon` come sessione utente, non la Bot API classica
- il bot apre un ordine per ogni TP trovato nel messaggio e gestisce i livelli in modo progressivo
- il parser ignora messaggi non riconosciuti come commenti motivazionali o testo libero
