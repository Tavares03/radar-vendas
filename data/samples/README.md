# Amostras sintéticas

Conversas de exemplo usadas pela demo (`RADAR_SEED_DEMO=true`), pelos testes e pelo Space.

**Tudo aqui é sintético.** Nomes, telefones, CPFs e empresas foram gerados pelo módulo
[`synthetic/`](../../synthetic); os CPFs e CNPJs são matematicamente válidos, mas não pertencem
a ninguém. Não coloque conversas reais nesta pasta.

## `synthetic/`

Dez exports do WhatsApp (`.zip`), dois por setor, um com vendedor problemático e outro com
vendedor bom ou médio, e `anotacoes.jsonl` com a verdade de referência de cada um (rótulos por
mensagem, dados pessoais com posição e alertas esperados). Regenere com
`uv run radar-synth samples`. Os áudios dos zips são arquivos falsos acompanhados da transcrição
(`<áudio>.txt`), que o Radar usa no lugar do Whisper.

## `audio/`

Notas de voz no formato do WhatsApp (Ogg/Opus, mono, 16 kHz) para testar a transcrição de ponta
a ponta. São **fala sintética** (TTS), não a voz de uma pessoa:

| Arquivo | Quem fala | O que diz |
|---|---|---|
| `cliente-pede-simulacao.opus` | cliente | pergunta o valor da parcela e pede uma simulação |
| `vendedor-promete-contemplacao.opus` | vendedor | promete contemplação no primeiro mês (risco) |
