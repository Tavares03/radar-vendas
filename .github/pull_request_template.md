## O que muda

<!-- Uma ou duas frases. Se fecha uma issue: "Fecha #123". -->

## Como foi testado

<!-- Testes novos, comandos rodados, telas verificadas. -->

## Checklist

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy backend/src synthetic/src evals/src`
- [ ] `uv run pytest`
- [ ] Frontend (se mexeu): `npm run lint && npm run typecheck && npm run build`
- [ ] Mudou modelo de banco? Migration incluída e revisada
- [ ] **Nenhum dado real** de pessoas ou empresas em código, testes ou exemplos
- [ ] Documentação e `CHANGELOG.md` atualizados, se aplicável
