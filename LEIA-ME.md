# LEIA-ME — o que é este branch

Este branch (`cofre`) é um **vault do Obsidian**: a memória de longo prazo do
projeto Pokémon RPG. Ele tem **história separada** do código (branch órfão) —
aqui só existem notas markdown, nunca código do jogo.

- O código vive no branch `main` (auto-deployado no Render).
- As notas vivem aqui. Push neste branch **não dispara deploy nenhum**.
- Quem escreve: o Claude (durante as sessões de desenvolvimento, commit
  direto sem PR) e você (pelo Obsidian, via plugin Fit).

Ponto de entrada: [[00-Indice]].

## Como sincronizar com o app do Obsidian (plugin Fit)

O [Fit](https://github.com/joshuakto/fit) sincroniza via API do GitHub, sem
precisar de git instalado — funciona no celular.

1. **Crie um vault novo e vazio** no Obsidian (não use um vault existente).
2. Settings → Community plugins → Browse → instale e ative o **Fit**.
3. No GitHub: Settings → Developer settings → **Fine-grained personal access
   tokens** → Generate new token:
   - Repository access: **só** `ijunior00/pokemon-RPG`;
   - Permissions → Repository permissions → **Contents: Read and write**
     (nada mais).
4. Nas settings do Fit: cole o token → o campo de repositório carrega →
   escolha `pokemon-RPG` e o branch **`cofre`** (⚠️ nunca `main` — o main tem
   2.000+ arquivos de código/sprites e é o deploy de produção).
5. Clique no ícone do Fit para sincronizar. As notas descem pro app; suas
   edições sobem pra cá.

### Avisos

- **Não compartilhe** o arquivo de settings do plugin (contém seu token).
- Conflitos (mesma nota editada dos dois lados) o Fit resolve guardando a
  versão remota em `_fit/` — essa pasta é ignorada pelo git.
- Config local do app (`.obsidian/workspace*.json`, plugins) não é versionada.
