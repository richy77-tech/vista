# Sicurezza — TRADING NEWS AI

Questo repo e' **pubblico** e fa girare un bot che pubblica su Telegram.
Regola numero uno: nel repo non entra mai un secret.

## Cosa e' successo (28/09/2026) — incidente e correzione

- Un file `.env` con il token del bot (`TELEGRAM_BOT_TOKEN`) e' stato committato
  nel repo pubblico (commit `9718a55`).
- Il token e' stato usato da terzi: la descrizione di `@Richynews_bot` e' stata
  riscritta con spam in russo.
- **Correzione:** token revocato su BotFather, nuovo token consegnato fuori
  banda (chat privata, mai nel repo), secret GitHub `TELEGRAM_BOT_TOKEN`
  aggiornato. Il `.env` e' stato rimesso in `.gitignore` e rimosso dal tracking.

Il token vecchio resta nella storia git, ma **e' revocato**: e' inerte. Non si
riscrive la storia di un repo che fa auto-commit ogni 20 minuti per ripulirlo.

## Difese attive

1. `.gitignore` copre `.env` e tutti i file di stato locale.
2. **Secret guard nel workflow** (`tn.yml`): prima di ogni `git commit` il job
   scansiona il diff in staging e **annulla il commit** se trova qualcosa che
   somiglia a un token (bot token, `ghp_`, `github_pat_`, `sk-`).
3. I secret vivono solo nei GitHub Actions secrets: `TELEGRAM_BOT_TOKEN`,
   `TG_CHAT`, `VISTA_AFFILIATE`, `TN_DISPATCH_TOKEN`.
4. Il codice legge la configurazione da variabili d'ambiente; il `.env` locale
   e' solo per lo sviluppo e non viene mai committato.

## Regole per chi tocca questo repo

- Mai incollare token, password o chiavi in file, commit, log o issue.
- Se un token finisce in un commit: **revocarlo subito** (non basta cancellare il
  file), poi emetterne uno nuovo e aggiornare il secret.
- Ruotare il token periodicamente da BotFather e aggiornare il secret.
- Il repo e' pubblico: trattare ogni push come visibile a tutti, per sempre.

## Segnalazioni

Questo e' un progetto personale. Per segnalare un problema di sicurezza,
contattare il proprietario dell'account GitHub.
