# ✅ Qualidade — notion-starter

Este documento registra o gate de qualidade do módulo e as exceções motivadas ao
[Felixo System Design](https://github.com/Felipe-Alcantara/Felixo-System-Design).

## Gate local

Execute na raiz do repositório:

```bash
python -m ruff check .
python -m pytest
```

Os testes não exigem token nem acesso à rede. A CI em
`.github/workflows/ci.yml` executa o mesmo gate em Python 3.10–3.13 para pushes no
`main` e pull requests.

## Critério de pronto

Uma mudança está pronta quando:

- lint e suíte automatizada passam;
- contratos públicos e fronteiras de camada foram preservados ou documentados;
- nenhum segredo, ID real ou banco local foi versionado;
- README, `IA.md` e testes foram atualizados quando afetados;
- riscos ou limitações restantes foram registrados.

## Exceção motivada: versões mínimas

O `pyproject.toml` usa limites mínimos (`>=`) nas dependências. Esta é uma
exceção deliberada à recomendação geral de pinagem: como o `notion-starter` é uma
biblioteca instalada no ambiente de outras aplicações, pins exatos poderiam
entrar em conflito com os consumidores e impedir uma resolução compatível.

A compatibilidade é verificada continuamente pela matriz da CI em Python
3.10–3.13. Aplicações consumidoras continuam responsáveis por fixar o ambiente
final com seu próprio lockfile quando precisarem de builds reproduzíveis.
