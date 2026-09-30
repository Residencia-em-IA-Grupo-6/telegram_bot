# Telegram Bot - Checagem de Mensagens e Fatos (Interface Crua)

Bot minimalista para receber mensagens, afirmações ou notícias no Telegram, consultar a API de IA do back-end e retornar o veredito de veracidade de forma crua e direta.

---

## ⚙️ Configuração

1. Instale as dependências:
```bash
pip install -r requirements.txt
```

2. Crie o arquivo `.env`:
```bash
cp .env.example .env
```
Edite com seu token gerado no `@BotFather`:
```env
TELEGRAM_BOT_TOKEN=seu_token_aqui
BACKEND_API_URL=http://localhost:8000/api/analyze
USE_MOCK=true
```

---

## ▶️ Execução

```bash
python bot.py
```

---

## 📤 Formato de Resposta (Crua)

O usuário envia ou encaminha qualquer mensagem (ex: *"Urgente! Governo anuncia confisco da poupança"*). O bot processa e responde:

```text
Fato/Texto: Urgente! Governo anuncia confisco da poupança...
Veredito: FAKE
Confiança: 93%
Resumo: Afirmação falsa ou desmentida por agências de checagem.
Motivos:
- Linguagem apelativa ou alarmista com pedidos de repasse.
- Inconsistência factual com dados públicos e órgãos oficiais.
Fontes:
- Agência Lupa
- Aos Fatos
- Projeto Comprova
```

---

## 📡 Contrato com o Back-end

- **Método:** `POST`
- **Payload enviado:**
  ```json
  {
    "text": "Texto completo da mensagem ou fato a ser verificado",
    "urls": ["https://..."],
    "user_id": 123456789,
    "chat_id": 987654321
  }
  ```
- **JSON esperado da API:**
  ```json
  {
    "claim": "Resumo do fato/mensagem",
    "verdict": "FAKE",
    "confidence": 0.93,
    "summary": "...",
    "reasons": ["motivo 1", "motivo 2"],
    "sources": ["fonte 1", "fonte 2"]
  }
  ```
