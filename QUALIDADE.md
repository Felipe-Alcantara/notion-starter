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

## Fluxos destrutivos

Operações que apagam conteúdo do workspace seguem um contrato verificado por
testes que falham sem a correção:

- **validar antes de escrever** — tipo, filhos e limites documentados da API
  (`content.validar_blocos`) são conferidos sem rede; a recusa acontece antes de
  qualquer chamada de escrita;
- **escrever antes de apagar** — o conteúdo novo (ou a cópia, no reordenar) é
  gravado e confirmado antes de o antigo ir para a lixeira; se um lote falhar, o
  que foi criado é desfeito;
- **lista branca, não lista negra** — só se apaga/recria o que a biblioteca sabe
  recriar; o resto é preservado com o motivo;
- **rastro para desfazer** — os IDs apagados voltam no resultado e nas exceções
  (`LimpezaIncompletaError`, `EscritaParcialError`, `ReordenacaoIncompletaError`),
  e `restaurar_blocos` usa esses IDs;
- **backups fora do diretório corrente** — ficam na pasta de estado do usuário,
  só com permissão do dono, para nunca entrarem num repositório.

Leitura e escrita de Markdown precisam concordar: o que `blocos_para_markdown`
devolve é o que quem confere uma edição vê e o que uma reescrita regrava. Por
isso o código de um bloco `code` sai da leitura sem `strip()` (só as quebras de
linha das pontas, o mesmo corte da escrita), e um teste de ida e volta com a
primeira linha recuada guarda esse contrato.

Os *fakes* desses testes imitam a API real (ordem de filhos, `position`,
`results` com os irmãos seguintes, 400 nos limites) e o comportamento foi
conferido numa página-sandbox do workspace real antes do registro no `IA.md`.
Todas as exceções da biblioteca derivam de `NotionSyncError`; as que antes
herdavam de `ValueError`/`RuntimeError` mantêm essa base como segunda, para não
quebrar os consumidores.

## Exceção motivada: versões mínimas

O `pyproject.toml` usa limites mínimos (`>=`) nas dependências. Esta é uma
exceção deliberada à recomendação geral de pinagem: como o `notion-starter` é uma
biblioteca instalada no ambiente de outras aplicações, pins exatos poderiam
entrar em conflito com os consumidores e impedir uma resolução compatível.

A compatibilidade é verificada continuamente pela matriz da CI em Python
3.10–3.13. Aplicações consumidoras continuam responsáveis por fixar o ambiente
final com seu próprio lockfile quando precisarem de builds reproduzíveis.

## Distribuição

O `pyproject.toml` é a fonte do pacote público `notion-starter` (`0.4.0`, release
pendente; o PyPI serve `0.3.1` até a tag `v0.4.0`), com wheel e sdist validados
por `twine check` e publicados no
[PyPI](https://pypi.org/project/notion-starter/). `__version__` e o
`pyproject.toml` andam juntos (`tests/test_versao.py`). API pública nova sai em
versão nova **antes** de um consumidor depender dela: o número publicado é o
único contrato que a faixa de dependência da CLI e do app enxerga. O artefato não leva tokens,
perfis locais ou banco SQLite. O consumidor que precisa do produto completo deve
instalar a fachada `notion-automacoes[app]`, não adicionar dependências Git.

## Documentação

Mudanças de API pública, dependências, exemplos ou distribuição exigem atualização
do `README.md` e de `IA.md` no mesmo passo. Exemplos usam placeholders; não
incluem tokens, IDs reais, caminhos privados ou arquivos gerados.

O helper de classificação em lote mantém o *dry-run* como comportamento padrão:
qualquer aplicação precisa de um callback ou de um cliente/coluna explícitos.
Esse contrato evita que um relatório de distribuição altere linhas por acidente.
