# Verificador de Verdade — MVP com IA

Site simples em Flask para triagem automática de confiabilidade de páginas web.

## O que mudou nesta versão

Esta versão corrige o problema em que muitos sites terminavam com o mesmo resultado, como 34%. O cálculo local agora é mais dinâmico e considera mais sinais da página. Além disso, foi adicionada uma camada opcional de IA: quando `OPENAI_API_KEY` está configurada, o sistema envia o conteúdo extraído para uma análise estruturada e retorna pontos possivelmente reais, não verificados, suspeitos ou falsos.

## O que ele faz

- Recebe um link informado pelo usuário.
- Acessa a página e extrai título, descrição, autor/fonte, data e texto principal.
- Identifica afirmações verificáveis no conteúdo.
- Analisa sinais locais de confiabilidade: HTTPS, domínio, autoria, data, fontes oficiais/acadêmicas, diversidade de links, linguagem sensacionalista, afirmações absolutas e marcação ClaimReview.
- Pode consultar a Google Fact Check Tools API se você configurar `GOOGLE_FACTCHECK_API_KEY`.
- Pode consultar IA via OpenAI se você configurar `OPENAI_API_KEY`.
- Mostra três pontuações: índice final, pontuação local e pontuação da IA.
- Exibe o que parece real/verificável, o que não foi verificado e o que parece suspeito, exagerado ou falso.

## Limite ético e técnico

O sistema não determina a verdade absoluta de uma notícia. Ele produz uma estimativa de confiabilidade e verificabilidade. A IA também não deve ser tratada como autoridade final, principalmente quando a página não oferece fontes verificáveis. O resultado deve ser usado como triagem inicial.

## Como rodar localmente

```bash
cd verificador_verdade_mvp
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Abra no navegador:

```text
http://127.0.0.1:5000
```

## Como ativar a análise por IA

Crie um arquivo `.env` na raiz do projeto, usando o `.env.example` como modelo:

```env
OPENAI_API_KEY=sua_chave_aqui
OPENAI_MODEL=gpt-5.4-mini
```

Depois rode novamente:

```bash
python app.py
```

Quando a IA estiver ativa, a tela mostrará:

- Modo: `IA + heurística local`;
- pontuação local;
- pontuação da IA;
- síntese da IA;
- pontos possivelmente reais/verificáveis;
- pontos não verificados;
- pontos suspeitos, exagerados ou falsos;
- recomendações de checagem.

## Como ativar checagens externas do Google Fact Check

Também no arquivo `.env`, adicione:

```env
GOOGLE_FACTCHECK_API_KEY=sua_chave_aqui
```

Sem essa chave, o sistema ainda funciona, mas não consulta a base externa do Google Fact Check Tools.

## Por que antes dava 34% em quase tudo?

A versão anterior fazia uma conta muito rígida. Em páginas comuns, geralmente apareciam os mesmos sinais:

- tinha HTTPS: somava pontos;
- não encontrava autor: perdia pontos;
- não encontrava data: perdia pontos;
- não encontrava fontes oficiais: perdia pontos;
- tinha texto suficiente: somava poucos pontos.

Essa combinação frequentemente levava ao mesmo resultado. Agora o sistema considera mais fatores e, quando configurado, usa IA para avaliar o conteúdo de forma contextual.

## Estrutura

```text
verificador_verdade_mvp/
├── app.py
├── requirements.txt
├── .env.example
├── README.md
├── templates/
│   └── index.html
└── static/
    ├── app.js
    └── style.css
```

## Próximos módulos recomendados

1. Banco de dados para salvar análises feitas pelos usuários.
2. Histórico público de checagens.
3. Login e painel administrativo.
4. Revisão humana de análises sensíveis.
5. Base própria de domínios confiáveis, suspeitos e bloqueados.
6. Relatório em PDF.
7. Busca automática em fontes oficiais por tema: saúde, legislação, economia, ciência, educação e política pública.
