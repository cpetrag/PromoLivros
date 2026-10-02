# 📚 Documentação Completa: Sistema de Conversão de Links de Afiliado

## 📋 Índice
1. [Visão Geral](#visão-geral)
2. [Arquitetura do Sistema](#arquitetura-do-sistema)
3. [Fluxo de Conversão](#fluxo-de-conversão)
4. [Detecção de Lojas](#detecção-de-lojas)
5. [Monetização por Rede](#monetização-por-rede)
6. [Encurtamento de Links](#encurtamento-de-links)
7. [Resolução de Redirecionadores](#resolução-de-redirecionadores)
8. [Configurações e Credenciais](#configurações-e-credenciais)
9. [Exemplos Práticos](#exemplos-práticos)

---

## 🎯 Visão Geral

O `AffiliateManager` é o sistema central responsável por converter links de produtos em links de afiliado monetizados. Ele detecta automaticamente a loja, aplica a regra de afiliação correta e, opcionalmente, encurta o link final.

### Funcionalidades Principais:
- ✅ Detecção automática de loja/rede de afiliados
- ✅ Conversão para múltiplas redes (Awin, Rakuten, CityAds, Amazon, Shopee, etc.)
- ✅ Resolução de redirecionadores (Promobit, Pelando, etc.)
- ✅ Encurtamento automático de links
- ✅ Cache e tratamento de erros

---

## 🏗️ Arquitetura do Sistema

```
┌─────────────────────────────────────────────────────────┐
│              AffiliateManager.gerarLink()               │
│                    (Ponto de Entrada)                    │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │  1. Resolver Redirecionador  │
        │     (se necessário)           │
        └──────────────┬───────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │  2. Detectar Loja/Rede        │
        │     detectingLogic()         │
        └──────────────┬───────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │  3. Rotear para Monetizador  │
        │     (switch por rede)        │
        └──────────────┬───────────────┘
                       │
        ┌──────────────┴───────────────┐
        │                              │
        ▼                              ▼
┌───────────────┐            ┌──────────────────┐
│ Monetizador   │            │ Monetizador      │
│ Específico    │    ...     │ Específico      │
│ (Awin, etc)   │            │ (Shopee, etc)   │
└───────┬───────┘            └────────┬─────────┘
        │                              │
        └──────────────┬───────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │  4. Encurtar Link (opcional)  │
        │     encurtarLink()            │
        └──────────────┬───────────────┘
                       │
                       ▼
              Link Final Monetizado
```

---

## 🔄 Fluxo de Conversão

### Passo a Passo Detalhado

#### 1. **Entrada: `gerarLink(linkOriginal)`**

```javascript
const resultado = await AffiliateManager.gerarLink('https://www.drogasil.com.br/produto');
```

#### 2. **Resolução de Redirecionadores**

Se o link for um redirecionador (Promobit, Pelando, etc.), o sistema resolve primeiro:

```javascript
if (this.precisaResolver(linkOriginal)) {
    linkProcessamento = await this.resolverLinkFinal(linkOriginal);
}
```

**Domínios que exigem resolução:**
- `promobit.com.br`
- `pelando.com.br`
- `gatry.com`
- `webtrack.com.br`
- `divulgador.magalu.com`
- Links com `/Redirect/to/`
- Links com `/sec/` ou `/social/` (Mercado Livre)

#### 3. **Detecção da Loja/Rede**

O sistema analisa o hostname e identifica a rede de afiliados:

```javascript
const deteccao = this.detectingLogic(linkProcessamento);
// Retorna: { rede: 'cityads', dominio: 'drogariaspacheco.com.br', baseUrl: '...' }
```

#### 4. **Roteamento para Monetizador**

Baseado na rede detectada, chama o monetizador específico:

```javascript
switch (deteccao.rede) {
    case 'cityads': 
        resultado = this.monetizarCityAds(link, deteccao.baseUrl);
        break;
    case 'awin': 
        resultado = this.monetizarAwin(link, deteccao.mid);
        break;
    // ... outros casos
}
```

#### 5. **Encurtamento (Opcional)**

Após a conversão, o link pode ser encurtado:

```javascript
const linkEncurtado = await AffiliateManager.encurtarLink(resultado.link);
```

---

## 🔍 Detecção de Lojas

### Ordem de Verificação

A função `detectingLogic()` verifica as lojas nesta ordem:

1. **CityAds** (prioridade alta - verifica primeiro)
   - `drogariaspacheco.com.br` → Pacheco
   - `drogariasaopaulo.com.br` → Drogaria São Paulo
   - `drogal.com.br` → Drogal
   - `pacheco.com.br` → Pacheco (alternativo)

2. **Clube** (links já encurtados)
   - `clube.baby`
   - `clube.promo`

3. **Shopee**
   - `shopee.com.br`
   - `shope.ee`

4. **Amazon**
   - `amazon.com.br`
   - `amzn.to`
   - `amzlink.to`

5. **Natura**
   - `natura.com.br`
   - `minhaloja.natura.com.br`

6. **Mercado Livre**
   - `mercadolivre.com.br`
   - `produto.mercadolivre.com.br`

7. **Magalu**
   - `magazineluiza.com.br`
   - `magazinevoce.com.br`
   - `divulgador.magalu.com`
   - `influenciadormagalu.com.br`

8. **Awin** (via `merchants.json`)
   - Busca no arquivo `merchants.json` na seção `awin`
   - Retorna o MID (Merchant ID) correspondente

9. **Rakuten** (via `merchants.json`)
   - Busca no arquivo `merchants.json` na seção `rakuten`
   - Retorna o MID correspondente

10. **Desconhecida**
    - Se nenhuma rede for detectada, retorna `{ rede: 'desconhecida', dominio: hostname }`

### Exemplo de Detecção

```javascript
// Link: https://www.drogariaspacheco.com.br/produto
const deteccao = AffiliateManager.detectingLogic(link);
// Resultado:
// {
//   rede: 'cityads',
//   dominio: 'drogariaspacheco.com.br',
//   baseUrl: 'https://whjre.com/v2/click-BJM6Y-oqOpa-RyQME-317e0a23?tl=1&sa=babypoupe&url='
// }
```

---

## 💰 Monetização por Rede

### 1. CityAds

**Lojas suportadas:**
- Drogaria São Paulo
- Drogarias Pacheco
- Drogal

**Formato do link:**
```
BASE_URL + encodeURIComponent(link_original)
```

**Exemplo:**
```javascript
// Entrada: https://www.drogariaspacheco.com.br/fralda-huggies/p
// Base URL: https://whjre.com/v2/click-BJM6Y-oqOpa-RyQME-317e0a23?tl=1&sa=babypoupe&url=
// Saída: https://whjre.com/v2/click-BJM6Y-oqOpa-RyQME-317e0a23?tl=1&sa=babypoupe&url=https%3A%2F%2Fwww.drogariaspacheco.com.br%2Ffralda-huggies%2Fp
```

**Configuração:**
```javascript
const CITYADS_LOJAS = {
    'drogariasaopaulo.com.br': 'https://whjre.com/v2/click-bQK2E-oqOpa-pdgQq-bd0c8404?tl=1&sa=babypoupe&url=',
    'drogariaspacheco.com.br': 'https://whjre.com/v2/click-BJM6Y-oqOpa-RyQME-317e0a23?tl=1&sa=babypoupe&url=',
    'drogal.com.br': 'https://whjre.com/v2/click-3y0vr-oqOpa-pd74w-803fb304?tl=1&sa=babypoupe&url='
};
```

---

### 2. Awin

**Formato do link:**
```
https://www.awin1.com/cread.php?awinmid={MID}&awinaffid={AFFILIATE_ID}&clickref={CLICKREF}&ued={LINK_ENCODED}
```

**Parâmetros:**
- `awinmid`: Merchant ID (vem do `merchants.json`)
- `awinaffid`: ID do afiliado fixo (`667913`)
- `clickref`: Referência (`babypoupe`)
- `ued`: Link original (URL encoded)

**Exemplo:**
```javascript
// Entrada: https://www.loja.com.br/produto
// MID: 12345 (do merchants.json)
// Saída: https://www.awin1.com/cread.php?awinmid=12345&awinaffid=667913&clickref=babypoupe&ued=https%3A%2F%2Fwww.loja.com.br%2Fproduto
```

**Configuração:**
- `AWIN_AFFILIATE_ID`: `'667913'`
- `CLICKREF`: `'babypoupe'`
- MID vem de `merchants.json` → `awin.{loja}`

---

### 3. Rakuten

**Formato do link:**
```
https://click.linksynergy.com/deeplink?id={AFFILIATE_ID}&mid={MID}&murl={LINK_ENCODED}&u1={CLICKREF}
```

**Parâmetros:**
- `id`: ID do afiliado fixo (`rn5AhjM4E9Q`)
- `mid`: Merchant ID (vem do `merchants.json`)
- `murl`: Link original (URL encoded)
- `u1`: Referência (`babypoupe`)

**Exemplo:**
```javascript
// Entrada: https://www.loja.com.br/produto
// MID: 67890 (do merchants.json)
// Saída: https://click.linksynergy.com/deeplink?id=rn5AhjM4E9Q&mid=67890&murl=https%3A%2F%2Fwww.loja.com.br%2Fproduto&u1=babypoupe
```

**Configuração:**
- `RAKUTEN_AFFILIATE_ID`: `'rn5AhjM4E9Q'`
- `CLICKREF`: `'babypoupe'`
- MID vem de `merchants.json` → `rakuten.{loja}`

---

### 4. Amazon

**Formato do link:**
```
https://www.amazon.com.br/dp/{ASIN}?tag={TAG}
```

**Processo:**
1. Se o link for encurtado (`amzn.to`, `amzlink.to`), resolve primeiro
2. Extrai o ASIN (código de 10 caracteres) do link
3. Adiciona o parâmetro `tag` com o ID de afiliado

**Exemplo:**
```javascript
// Entrada: https://www.amazon.com.br/dp/B08XYZ1234
// Saída: https://www.amazon.com.br/dp/B08XYZ1234?tag=babypoupe-20
```

**Configuração:**
- `AMAZON_TAG`: `'babypoupe-20'`

**Parâmetros preservados:**
- `tag`, `linkCode`, `ref_`, `ref`, `language`, `k`, `i`, `rh`, `node`

---

### 5. Shopee

**Processo:**
1. Usa API GraphQL da Shopee
2. Gera assinatura HMAC SHA256
3. Cria link curto via API

**Formato da requisição:**
```javascript
mutation ($input: ShortLinkInput!) {
  generateShortLink(input: $input) {
    shortLink
  }
}
```

**Autenticação:**
- `SHA256 Credential={APP_ID}, Timestamp={TIMESTAMP}, Signature={HMAC_SHA256}`

**Configuração:**
- `SHOPEE_APP_ID`: do `.env`
- `SHOPEE_SECRET`: do `.env`
- `CLICKREF`: `'babypoupe'`

---

### 6. Mercado Livre

**Processo:**
1. Usa API interna do Mercado Livre
2. Requer cookie e CSRF token válidos
3. Gera link curto via API

**Endpoint:**
```
POST https://www.mercadolivre.com.br/affiliate-program/api/v2/stripe/user/links
```

**Headers:**
- `x-csrf-token`: CSRF token
- `cookie`: Cookie de sessão

**Body:**
```json
{
  "tag": "cpetrag1971",
  "url": "https://produto.mercadolivre.com.br/MLB-123456789"
}
```

**Configuração:**
- `ML_COOKIE`: do `.env`
- `ML_CSRF`: do `.env`
- `ML_TAG`: `'cpetrag1971'`

---

### 7. Magalu

**Processo:**
1. Limpa o path do link
2. Adiciona parâmetros `promoter_id` e `partner_id`
3. Preserva `seller_id` se existir

**Formato do link:**
```
https://www.magazineluiza.com.br/{path}/?promoter_id={PROMOTER}&partner_id={PARTNER}&seller_id={SELLER}
```

**Exemplo:**
```javascript
// Entrada: https://www.magazineluiza.com.br/fralda-huggies/p/ABC123
// Saída: https://www.magazineluiza.com.br/fralda-huggies/divulgador/oferta/ABC123/?promoter_id=93201&partner_id=3440
```

**Configuração:**
- `MAGALU_PROMOTER`: `'93201'`
- `MAGALU_PARTNER`: `'3440'`

---

### 8. Natura

**Processo:**
1. Normaliza hostname para `www.minhaloja.natura.com.br`
2. Adiciona parâmetro `consultoria`

**Formato do link:**
```
https://www.minhaloja.natura.com.br/{path}?consultoria={CONSULTORIA}
```

**Exemplo:**
```javascript
// Entrada: https://natura.com.br/produto
// Saída: https://www.minhaloja.natura.com.br/produto?consultoria=pechincheiro
```

**Configuração:**
- `NATURA_CONSULTORIA`: `'pechincheiro'`

---

## ✂️ Encurtamento de Links

### Função: `encurtarLink(url)`

**Endpoint:**
```
POST https://fwnkehssnqs2b5jglm5qfsfd2e0uwbtc.lambda-url.sa-east-1.on.aws/
```

**Headers:**
- `Content-Type`: `application/json`
- `x-api-key`: `cpromos`

**Body:**
```json
{
  "domain": "descontos.ai",
  "url": "https://link-afiliado-completo.com/..."
}
```

**Resposta:**
```json
{
  "shortUrl": "https://descontos.ai/abc123"
}
```

### Regras de Encurtamento

1. **Não encurta se já for link curto:**
   - Links que contêm `descontos.ai`
   - Links que contêm `clube.baby`
   - Links que contêm `clube.promo`

2. **Tratamento de erros:**
   - Se a API falhar, retorna o link original
   - Se não retornar `shortUrl`, retorna o link original

### Exemplo:

```javascript
// Entrada: https://whjre.com/v2/click-BJM6Y-oqOpa-RyQME-317e0a23?tl=1&sa=babypoupe&url=https%3A%2F%2Fwww.drogariaspacheco.com.br%2Fproduto
// Saída: https://descontos.ai/tLxy2T
```

---

## 🔗 Resolução de Redirecionadores

### Função: `resolverLinkFinal(url)`

Resolve links de redirecionadores para obter o link final do produto.

### Domínios Suportados:

1. **Promobit**
   - Extrai link do HTML usando seletores CSS
   - Segue redirects recursivos

2. **Pelando**
   - Similar ao Promobit

3. **Mercado Livre (`/sec/`, `/social/`)**
   - Extrai link do HTML
   - Usa regex para encontrar links de produto

4. **Magalu (`divulgador.magalu.com`)**
   - Segue redirects HTTP
   - Retorna URL final após redirect

5. **Gatry**
   - Extrai link do HTML

### Seletores CSS Usados:

```javascript
const selectors = [
    "div.poly-action-links__action a",
    "div.poly-action-links_action a",
    "a.poly-component__link-action-link",
    "a.poly-component__link"
];
```

### Exemplo:

```javascript
// Entrada: https://www.promobit.com.br/ofertas/fralda-huggies-12345
// Processo:
// 1. Faz fetch do HTML
// 2. Procura por seletores CSS
// 3. Encontra link do Mercado Livre
// Saída: https://produto.mercadolivre.com.br/MLB-123456789
```

---

## ⚙️ Configurações e Credenciais

### Variáveis de Ambiente (`.env`)

```env
# Shopee
SHOPEE_APP_ID=seu_app_id
SHOPEE_SECRET=seu_secret

# Mercado Livre
ML_COOKIE=seu_cookie
ML_CSRF=seu_csrf_token
ML_TAG=cpetrag1971
```

### IDs Fixos (no código)

```javascript
const AWIN_AFFILIATE_ID = '667913';
const RAKUTEN_AFFILIATE_ID = 'rn5AhjM4E9Q';
const AMAZON_TAG = 'babypoupe-20';
const NATURA_CONSULTORIA = 'pechincheiro';
const CLICKREF = 'babypoupe';
const MAGALU_PROMOTER = '93201';
const MAGALU_PARTNER = '3440';
```

### Arquivo `merchants.json`

```json
{
  "awin": {
    "loja1.com.br": "12345",
    "loja2.com.br": "67890"
  },
  "rakuten": {
    "loja3.com.br": "11111",
    "loja4.com.br": "22222"
  }
}
```

---

## 📝 Exemplos Práticos

### Exemplo 1: Drogaria São Paulo

```javascript
// Entrada
const link = 'https://www.drogariasaopaulo.com.br/fralda-huggies/p';

// Processo
const resultado = await AffiliateManager.gerarLink(link);
// 1. Detecta: CityAds
// 2. Monetiza: https://whjre.com/v2/click-bQK2E-oqOpa-pdgQq-bd0c8404?tl=1&sa=babypoupe&url=https%3A%2F%2Fwww.drogariasaopaulo.com.br%2Ffralda-huggies%2Fp

// Encurta
const linkFinal = await AffiliateManager.encurtarLink(resultado.link);
// Resultado: https://descontos.ai/abc123
```

### Exemplo 2: Drogarias Pacheco

```javascript
// Entrada
const link = 'https://www.drogariaspacheco.com.br/fralda-huggies/p';

// Processo
const resultado = await AffiliateManager.gerarLink(link);
// 1. Detecta: CityAds (Pacheco)
// 2. Monetiza: https://whjre.com/v2/click-BJM6Y-oqOpa-RyQME-317e0a23?tl=1&sa=babypoupe&url=https%3A%2F%2Fwww.drogariaspacheco.com.br%2Ffralda-huggies%2Fp

// Encurta
const linkFinal = await AffiliateManager.encurtarLink(resultado.link);
// Resultado: https://descontos.ai/xyz789
```

### Exemplo 3: Amazon

```javascript
// Entrada
const link = 'https://www.amazon.com.br/dp/B08XYZ1234';

// Processo
const resultado = await AffiliateManager.gerarLink(link);
// 1. Detecta: Amazon
// 2. Monetiza: https://www.amazon.com.br/dp/B08XYZ1234?tag=babypoupe-20

// Encurta
const linkFinal = await AffiliateManager.encurtarLink(resultado.link);
// Resultado: https://descontos.ai/def456
```

### Exemplo 4: Link com Redirecionador

```javascript
// Entrada (Promobit)
const link = 'https://www.promobit.com.br/ofertas/fralda-huggies-12345';

// Processo
const resultado = await AffiliateManager.gerarLink(link);
// 1. Detecta redirecionador → Resolve
// 2. Link resolvido: https://produto.mercadolivre.com.br/MLB-123456789
// 3. Detecta: Mercado Livre
// 4. Monetiza via API ML: https://mercadolivre.com.br/MLB-123456789?tag=cpetrag1971

// Encurta
const linkFinal = await AffiliateManager.encurtarLink(resultado.link);
// Resultado: https://descontos.ai/ghi789
```

---

## 🚀 Uso no Sistema

### Script: `converter_afiliados_produtos.js`

Este script processa produtos do banco de dados e converte seus links:

```javascript
// 1. Busca produtos sem link de afiliado
const produtos = buscarProdutosParaConverter(db, LIMITE_POR_EXECUCAO);

// 2. Para cada produto
for (const produto of produtos) {
    // 3. Converte link
    const resultado = await AffiliateManager.gerarLink(produto.link_original);
    
    // 4. Encurta
    const linkEncurtado = await AffiliateManager.encurtarLink(resultado.link);
    
    // 5. Atualiza no banco
    atualizarLinkAfiliado(db, produto.id, linkEncurtado);
}
```

### Execução Automática

O script roda automaticamente a cada 6 horas via PM2:

```bash
pm2 start src/converter_afiliados_produtos.js --name converter-afiliados
```

---

## 📊 Status de Conversão

O sistema retorna um objeto com status:

```javascript
{
    link: 'https://link-afiliado-final.com',
    status: '🟢 CityAds',  // ou '⚠️ Erro', '❌ Falha', etc.
    convertido: true
}
```

### Códigos de Status:

- `🟢 {Rede}`: Conversão bem-sucedida
- `⚠️ {Rede} (mensagem)`: Aviso (ex: sem credenciais)
- `❌ {Rede} (erro)`: Erro na conversão
- `🟡 Link Limpo`: Loja não suportada
- `✅ Clube (pronto)`: Link já é do clube

---

## 🔧 Manutenção e Extensibilidade

### Adicionar Nova Loja Awin/Rakuten

1. Adicione no `merchants.json`:
```json
{
  "awin": {
    "novaloja.com.br": "99999"
  }
}
```

2. O sistema detecta automaticamente!

### Adicionar Nova Loja CityAds

1. Adicione em `CITYADS_LOJAS`:
```javascript
const CITYADS_LOJAS = {
    // ... existentes
    'novaloja.com.br': 'https://whjre.com/v2/click-XXXXX-...?tl=1&sa=babypoupe&url='
};
```

2. O sistema detecta automaticamente!

### Adicionar Nova Rede

1. Adicione detecção em `detectingLogic()`:
```javascript
if (hostname.includes('novaloja.com')) {
    return { rede: 'novarede', dominio: hostname };
}
```

2. Adicione case no `gerarLink()`:
```javascript
case 'novarede':
    resultado = await this.monetizarNovaRede(linkProcessamento);
    break;
```

3. Implemente `monetizarNovaRede()`:
```javascript
static monetizarNovaRede(link) {
    // Sua lógica aqui
    return { link: linkConvertido, status: '🟢 Nova Rede' };
}
```

---

## 📌 Notas Importantes

1. **Rate Limiting**: O sistema tem delays entre requisições para evitar bloqueios
2. **Cache**: Links já convertidos podem ser cacheados
3. **Erros**: Sempre retorna o link original em caso de erro
4. **Encurtamento**: É opcional e pode ser desabilitado
5. **Credenciais**: Algumas redes requerem credenciais no `.env`

---

## 🐛 Troubleshooting

### Link não está sendo convertido

1. Verifique se a loja está na lista de detecção
2. Verifique se as credenciais estão no `.env`
3. Verifique os logs do console

### Link não está sendo encurtado

1. Verifique se o link já não é curto (`descontos.ai`, `clube.baby`)
2. Verifique se a API do encurtador está funcionando
3. Verifique os logs do console

### Erro 403 no Mercado Livre

1. Atualize o cookie e CSRF token no `.env`
2. Verifique se a sessão está válida

---

**Última atualização:** 31/12/2024  
**Versão:** 1.0

