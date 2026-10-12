# Telegram Bot - Checagem de Mensagens e Fatos (Interface Crua)

Bot minimalista para receber mensagens, afirmações ou notícias no Telegram, consultar a API de IA do back-end **FactChkBR** e retornar o veredito de veracidade de forma crua e direta.

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
BACKEND_HEALTH_URL=http://localhost:8000/api/health
BACKEND_TIMEOUT=60.0
USE_MOCK=false
OUTPUT_MODE=raw
```

---

## ▶️ Execução

```bash
python bot.py
```

---

## 💬 Comandos Disponíveis

* `/start` - Apresenta o bot e instruções iniciais de uso.
* `/health` - Consulta em tempo real a integridade da API FactChkBR, listando analisadores ativos e latência.
* `/help` - Guia detalhado de como enviar textos, notícias e links para análise.

---

## 📤 Formato de Resposta (Crua)

O usuário envia ou encaminha qualquer mensagem (ex: *"Existe adesivo emagrecedor com Mounjaro à venda por 39 reais"*). O bot processa e responde:

```text
Fato/Texto: Existe adesivo emagrecedor com Mounjaro à venda por 39 reais
Veredito: 🔴 FAKE
Confiança: 94%
Resumo: Afirmação falsa ou desmentida por agências de checagem e bases sanitárias.
Motivos:
- Medicamento Mounjaro (tirzepatida) possui administração exclusivamente injetável/subcutânea.
- Inexistência de aprovação sanitária (Anvisa) para formulações transdérmicas em adesivo.
- Ausência de registro de preço de 39 reais.
Fontes:
- Anvisa (Portal Oficial)
- Wikipedia (Ficha Farmacológica Oficial)
Detalhamento por Alegação:
- "Existe adesivo de Mounjaro" -> 🔴 FAKE (98%)
Avaliação de Riscos:
- Risco de fraude ou comercialização irregular.
- Risco à saúde por uso de substância clandestina.
```

---

## 📡 Contrato com o Back-end

- **Método:** `POST`
- **Endpoint:** `/api/analyze` (ou `/api/v1/analyze`)
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
    "sources": ["fonte 1", "fonte 2"],
    "sub_claims": [],
    "risks_assessment": []
  }
  ```

---

## 🧪 Testes Automatizados

Para executar os testes automatizados da integração:
```bash
pip install -r requirements-dev.txt
pytest tests/
```
