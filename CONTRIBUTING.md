# 🤝 Contribuindo com o notion-starter

Obrigado por querer contribuir! Este repositório é a biblioteca Python base do
ecossistema [Automações do Notion](https://github.com/Felipe-Alcantara/Automa-es-do-Notion):
cliente resiliente para a API do Notion, schema, tarefas, conteúdo, inventário e a
camada compartilhada `notion_starter.services`. Issues, correções de documentação,
novos helpers, exemplos, testes e melhorias de resiliência são bem-vindos.

> Contribuições devem preservar os contratos existentes, a documentação viva e o
> gate de qualidade descrito abaixo.

---

## 🚀 Como Contribuir

1. **Faça um fork** do repositório.
2. **Crie uma branch** descritiva (`fix/...`, `feat/...`, `docs/...`) para mudanças
   grandes; correções pequenas podem ir direto no `main` de quem mantém.
3. **Faça suas mudanças** seguindo os padrões abaixo.
4. **Rode os testes e o lint** antes de abrir o PR.
5. **Abra um Pull Request** explicando o que mudou e por quê.

Não tem certeza por onde começar? Abra uma issue descrevendo a ideia — a gente
conversa antes de você investir tempo no código.

---

## 🛠️ Ambiente de Desenvolvimento

```bash
git clone https://github.com/Felipe-Alcantara/notion-starter.git
cd notion-starter
pip install -e ".[dev]"

# Gate de qualidade (HTTP é mockado — não precisa de token nem rede)
ruff check .
python -m pytest
```

Requer Python 3.10+. Copie `.env.example` para `.env` apenas se for rodar os
exemplos de `examples/` contra um workspace real do Notion — nunca versione o `.env`.

---

## ✅ Padrões de Qualidade

- **Entenda o padrão existente antes de alterar.** Módulos coesos por
  responsabilidade: `client` (único que fala HTTP com o Notion), `schema`,
  `properties`/`readers`, `content`, `tasks`, `inventory`, `services` (casos de uso,
  sem HTTP próprio). Preserve essas fronteiras.
- **Prefira a solução mais simples** que resolva o problema real. A biblioteca tem
  poucas dependências de runtime de propósito.
- **Preserve contratos.** Assinaturas públicas, objetos (`Tarefa`, `RepoInfo`, ...) e
  exceções (`NotionSyncError` e derivadas) devem permanecer estáveis; mudança
  quebradora precisa ser explícita e documentada.
- **Tipos e validação.** `TypedDict` para payloads, `dataclass` para resultados;
  valide entradas externas.
- **Não exponha segredos.** Nada de tokens, IDs reais ou URLs privadas no código,
  nos testes ou na documentação.
- **Teste o comportamento.** Bugs corrigidos viram caso de regressão; HTTP é sempre
  mockado com `responses`.
- **Código, docstrings e mensagens de erro em português.**
- **Atualize a documentação viva** (`README.md` e `IA.md`) no mesmo passo quando a
  mudança alterar comportamento, estrutura ou comandos.

---

## ✍️ Padrões de Linguagem (Documentação e Logs)

- **Escreva para qualquer leitor** — linguagem geral e acessível, sem jargão interno.
- **Sem valores hardcoded** — use placeholders genéricos em vez de caminhos, tokens
  ou IDs reais.
- **Enquadre o trabalho futuro como convite à contribuição** em vez de uma lista de
  tarefas interna.

---

## 🔄 Fluxo de Pull Request

Um bom PR responde claramente:

- **O que mudou?**
- **Por que mudou?**
- **Como foi validado?** (ex.: `ruff check .` + `python -m pytest`)
- **Qual risco sobrou?**

Mantenha o PR focado: evite misturar refatoração ampla com novas funcionalidades.
Use commits pequenos no formato `tipo: descrição` (`feat`/`fix`/`docs`/`refactor`/`chore`).

---

## 💬 Código de Conduta

Seja respeitoso e acolhedor. Este é um espaço para aprender e construir juntos —
contribuições de pessoas de todos os níveis de experiência são bem-vindas.
