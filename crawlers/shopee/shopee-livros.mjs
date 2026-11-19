#!/usr/bin/env node
// Coletor diário de livros da Shopee -> CSV Atualizado/shopee-livros.csv. Não gera link de afiliado.
// Uso: node shopee-livros.mjs [--paginas N] [--consultas id1,id2] [--sem-pdp] [--saida pasta]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';

import { BOOKS_FACET, CATEGORIES, mapItem, mergeRow, pdpCandidates, pdpExtras, toCsv } from './lib/mapping.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const EXIT = { ok: 0, failure: 1, antibot: 2, session: 3, timeout: 4 };
const ERROR_ANTIBOT = 90309999;
const ERROR_END_OF_QUERY = 36801302;
const FULL_FILTER = { group_name: 'FAST_DELIVERY', values: ['channel_91007_stocked_br_product_label_filter'] };
const API_HEADERS = { 'x-api-source': 'pc', 'x-shopee-language': 'pt-BR', accept: 'application/json' };

class StopRun extends Error {
  constructor(reason, exitCode) {
    super(reason);
    this.exitCode = exitCode;
  }
}

function parseArgs(argv) {
  const args = { pages: null, only: null, pdp: true, output: null };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (flag === '--paginas') args.pages = Number(argv[++index]);
    else if (flag === '--consultas') args.only = new Set(String(argv[++index]).split(','));
    else if (flag === '--sem-pdp') args.pdp = false;
    else if (flag === '--saida') args.output = argv[++index];
  }
  return args;
}

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

function loadEnv(file) {
  // .env ao lado do script (chmod 600). Nada de segredo no código.
  if (!fs.existsSync(file)) return;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    const match = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (match && !process.env[match[1]]) process.env[match[1]] = match[2].replace(/^["']|["']$/g, '');
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const pause = ([min, max]) => sleep(min + Math.random() * (max - min));

function localStamp(date = new Date()) {
  const offset = -date.getTimezoneOffset();
  const sign = offset >= 0 ? '+' : '-';
  const pad = (value) => String(Math.trunc(Math.abs(value))).padStart(2, '0');
  const local = new Date(date.getTime() + offset * 60000).toISOString().slice(0, 19);
  return `${local}${sign}${pad(offset / 60)}:${pad(offset % 60)}`;
}

async function notify(text) {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chat = process.env.TELEGRAM_CHAT_ID;
  if (!token || !chat) return;
  try {
    await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ chat_id: chat, text: `Shopee livros: ${text}` }),
      signal: AbortSignal.timeout(15000),
    });
  } catch (error) {
    console.error('Alerta no Telegram falhou:', error.message);
  }
}

function expandQueries(config, only) {
  const excluded = new Set(config.excluir_facets_sub ?? []);
  const subFacets = Object.values(CATEGORIES).map((entry) => entry.facet).filter((facet) => !excluded.has(facet));
  const queries = [];
  for (const query of config.consultas ?? []) {
    if (query.facet === '*SUBCATEGORIAS*') {
      for (const facet of subFacets) queries.push({ ...query, id: `${query.id}-${facet}`, facet, keyword: config.keyword });
    } else {
      queries.push({ ...query, keyword: query.keyword ?? config.keyword });
    }
  }
  for (const extra of config.palavras_extras ?? []) {
    queries.push({ id: `extra-${extra.keyword}`, by: extra.by ?? 'sales', facet: extra.facet ?? BOOKS_FACET, keyword: extra.keyword });
  }
  return only ? queries.filter((query) => [...only].some((id) => query.id.startsWith(id))) : queries;
}

function searchParams(query, page) {
  const filters = [{ group_name: 'FACET', values: [query.facet] }];
  if (query.full) filters.push(FULL_FILTER);
  return {
    by: query.by,
    keyword: query.keyword,
    limit: 60,
    newest: page * 60,
    order: query.order ?? (query.by === 'price' ? 'asc' : 'desc'),
    page_type: 'search',
    scenario: 'PAGE_GLOBAL_SEARCH',
    version: 2,
    fe_filter_options: JSON.stringify(filters),
  };
}

function isAntibot(json) {
  if (!json) return false;
  if (json.error === ERROR_ANTIBOT) return true;
  // Resposta bloqueada vem só com chaves numéricas ("0","2","3","6") e sem itens.
  const keys = Object.keys(json);
  return keys.length > 0 && keys.every((key) => /^\d+$/.test(key));
}

async function apiGet(page, apiPath, params) {
  const url = `${apiPath}?${new URLSearchParams(params)}`;
  return page.evaluate(
    async ({ target, headers }) => {
      try {
        const response = await fetch(target, { credentials: 'include', headers });
        const text = await response.text();
        let json = null;
        try {
          json = JSON.parse(text);
        } catch {
          json = null;
        }
        return { status: response.status, json };
      } catch (error) {
        return { status: 0, json: null, error: String(error) };
      }
    },
    { target: url, headers: API_HEADERS },
  );
}

/** Modo B: a própria página da busca chama a API e nós só lemos a resposta. */
async function searchByNavigation(page, query, pageIndex) {
  const facet = query.full ? `${query.facet}` : query.facet;
  const url =
    `https://shopee.com.br/search?keyword=${encodeURIComponent(query.keyword)}&facet=${facet}` +
    `&sortBy=${query.by}&page=${pageIndex}`;
  const waiting = page.waitForResponse((response) => response.url().includes('/api/v4/search/search_items'), { timeout: 45000 });
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  const response = await waiting;
  return { status: response.status(), json: await response.json().catch(() => null) };
}

async function checkSession(page) {
  const url = page.url();
  if (url.includes('/verify/') || url.includes('/buyer/login')) {
    throw new StopRun(`sessão expirada ou verificação (${url.split('?')[0]})`, EXIT.session);
  }
}

class Collector {
  constructor(page, config, log) {
    this.page = page;
    this.config = config;
    this.log = log;
    this.rows = new Map();
    this.raw = new Map();
    this.mode = 'A';
    this.requests = 0;
    this.categories = { ...CATEGORIES, ...readJson(path.join(HERE, 'categorias-shopee.json'), {}) };
    this.unknownLeaves = new Map();
    this.leafOf = new Map();
  }

  skip(reason) {
    this.log.descartes[reason] = (this.log.descartes[reason] ?? 0) + 1;
  }

  get searchesLeft() {
    return this.requests < this.config.teto_buscas;
  }

  async fetchSearch(query, pageIndex) {
    this.requests += 1;
    const params = searchParams(query, pageIndex);
    if (this.mode === 'B') return searchByNavigation(this.page, query, pageIndex);
    let result = await apiGet(this.page, '/api/v4/search/search_items', params);
    if (isAntibot(result.json)) {
      this.log.erros.push({ consulta: query.id, pagina: pageIndex, erro: 'ANTIBOT no modo A; tentando modo B' });
      this.mode = 'B';
      await pause([8000, 12000]);
      result = await searchByNavigation(this.page, query, pageIndex);
      await checkSession(this.page);
    }
    return result;
  }

  async runQuery(query) {
    const stats = { consulta: query.id, paginas: 0, itens: 0, novos: 0 };
    for (let pageIndex = 0; pageIndex < this.config.paginas_por_consulta && this.searchesLeft; pageIndex += 1) {
      let result = await this.withBackoff(() => this.fetchSearch(query, pageIndex), query, pageIndex);
      if (!result) continue;
      let { json } = result;
      if (isAntibot(json)) throw new StopRun('ANTIBOT', EXIT.antibot);
      if (json?.error === ERROR_END_OF_QUERY) break;
      if ((json?.items?.length ?? 0) < 10 && json && !json.nomore) {
        await sleep(10000);
        result = await this.fetchSearch(query, pageIndex);
        json = result?.json;
        if (isAntibot(json)) throw new StopRun('ANTIBOT', EXIT.antibot);
      }
      stats.paginas += 1;
      for (const item of json?.items ?? []) {
        stats.itens += 1;
        if (this.take(item, query.id)) stats.novos += 1;
      }
      if (json?.nomore) break;
      await pause(this.config.pausa_busca_ms);
    }
    this.log.consultas.push(stats);
    console.log(`${query.id}: ${stats.paginas} páginas, ${stats.itens} itens, ${stats.novos} novos (total ${this.rows.size})`);
  }

  async withBackoff(call, query, pageIndex) {
    for (const wait of [0, 15000, 45000]) {
      if (wait) await sleep(wait);
      const result = await call();
      if (result?.status === 200 && result.json) return result;
      if (isAntibot(result?.json)) return result;
      this.log.erros.push({ consulta: query.id, pagina: pageIndex, status: result?.status ?? 0 });
    }
    return null;
  }

  take(item, origin) {
    const { row, skip, unknownLeaf, rawPrice } = mapItem(item, { categories: this.categories, origin, collectedAt: this.log.inicio });
    if (skip) {
      this.skip(skip);
      return false;
    }
    const existing = this.rows.get(row.asin);
    if (existing) {
      mergeRow(existing, row);
      this.skip('repetido');
      return false;
    }
    row.posicao = String(this.rows.size + 1);
    this.rows.set(row.asin, row);
    this.raw.set(row.asin, rawPrice);
    if (unknownLeaf) {
      this.leafOf.set(row.asin, unknownLeaf);
      if (!this.unknownLeaves.has(unknownLeaf)) this.unknownLeaves.set(unknownLeaf, row.asin);
    }
    return true;
  }

  async pdp(row) {
    const [shopId, itemId] = row.asin.split('.');
    const result = await apiGet(this.page, '/api/v4/pdp/get_pc', {
      item_id: itemId,
      shop_id: shopId,
      tz_offset_minutes: -180,
      detail_level: 0,
    });
    if (isAntibot(result.json)) throw new StopRun('ANTIBOT na PDP', EXIT.antibot);
    if (result.status !== 200 || !result.json?.data) return null;
    return pdpExtras(result.json, this.raw.get(row.asin) ?? 0);
  }

  async resolveUnknownLeaves() {
    // Uma PDP por folha nova, nunca por item. O nome fica no cache para os próximos dias.
    const cacheFile = path.join(HERE, 'categorias-shopee.json');
    const cache = readJson(cacheFile, {});
    for (const [leaf, asin] of this.unknownLeaves) {
      const extras = await this.pdp(this.rows.get(asin)).catch(() => null);
      await pause(this.config.pausa_pdp_ms);
      const name = extras?.leafName;
      this.log.folhas_novas.push({ catid: leaf, nome: name ?? '' });
      if (!name) continue;
      cache[leaf] = { name };
      this.categories[leaf] = { name };
      for (const row of this.rows.values()) {
        if (!row.categoria && this.leafOf.get(row.asin) === leaf) row.categoria = name;
      }
    }
    fs.writeFileSync(cacheFile, JSON.stringify(cache, null, 2));
    for (const row of this.rows.values()) {
      if (!row.categoria) {
        row.categoria = 'Outros';
        row.categoria_caminho = 'Livros e Revistas > Livros > Outros';
      } else if (!row.categoria_caminho) {
        row.categoria_caminho = `Livros e Revistas > Livros > ${row.categoria}`;
      }
    }
  }

  async enrich(limit) {
    let done = 0;
    for (const row of pdpCandidates([...this.rows.values()], limit)) {
      const extras = await this.pdp(row).catch((error) => {
        if (error instanceof StopRun) throw error;
        return null;
      });
      await pause(this.config.pausa_pdp_ms);
      if (!extras) continue;
      done += 1;
      if (extras.unavailable) {
        this.rows.delete(row.asin);
        this.skip('indisponivel_pdp');
        continue;
      }
      mergeRow(row, extras.row);
    }
    this.log.pdp = done;
  }
}

function writeOutput(rows, folder, day, { partial = false } = {}) {
  fs.mkdirSync(folder, { recursive: true });
  const ordered = [...rows].map((row, index) => ({ ...row, posicao: String(index + 1) }));
  const csv = toCsv(ordered);
  const dated = path.join(folder, `shopee-livros-${day}.csv${partial ? '.parcial' : ''}`);
  // .tmp + rename: o painel nunca lê arquivo pela metade.
  fs.writeFileSync(`${dated}.tmp`, csv);
  fs.renameSync(`${dated}.tmp`, dated);
  if (!partial) {
    const latest = path.join(folder, 'shopee-livros.csv');
    fs.writeFileSync(`${latest}.tmp`, csv);
    fs.renameSync(`${latest}.tmp`, latest);
  }
  return dated;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  loadEnv(path.join(HERE, '.env'));
  const config = {
    keyword: 'livro',
    paginas_por_consulta: 8,
    pausa_busca_ms: [2500, 4500],
    pausa_pdp_ms: [1500, 3000],
    teto_buscas: 250,
    timeout_min: 40,
    headless: false,
    ...readJson(path.join(HERE, 'config.shopee-livros.json'), {}),
  };
  if (args.pages) config.paginas_por_consulta = args.pages;
  const day = localStamp().slice(0, 10);
  const output = args.output ?? config.pasta_saida;
  if (!output) throw new Error('Defina pasta_saida no config.shopee-livros.json ou passe --saida.');
  const log = { inicio: localStamp(), consultas: [], descartes: {}, folhas_novas: [], erros: [], pdp: 0 };
  const logFile = path.join(HERE, 'logs', `shopee-livros-${day}.json`);
  fs.mkdirSync(path.dirname(logFile), { recursive: true });

  const context = await chromium.launchPersistentContext(path.join(HERE, 'profile'), {
    channel: 'chrome',
    headless: config.headless,
    locale: 'pt-BR',
    timezoneId: 'America/Sao_Paulo',
    viewport: { width: 1366, height: 860 },
  });
  const page = context.pages()[0] ?? (await context.newPage());
  const collector = new Collector(page, config, log);
  let exitCode = EXIT.ok;
  const deadline = setTimeout(() => {
    log.erros.push({ erro: `timeout de ${config.timeout_min} min` });
    finish(EXIT.timeout).finally(() => process.exit(EXIT.timeout));
  }, config.timeout_min * 60000);

  let finished = false;
  async function finish(code) {
    if (finished) return;
    finished = true;
    clearTimeout(deadline);
    log.fim = localStamp();
    log.itens = collector.rows.size;
    log.modo = collector.mode;
    log.buscas = collector.requests;
    log.exit = code;
    const partial = code !== EXIT.ok;
    if (collector.rows.size) log.arquivo = writeOutput(collector.rows.values(), partial ? path.join(HERE, 'out') : output, day, { partial });
    fs.writeFileSync(logFile, JSON.stringify(log, null, 2));
    await context.close().catch(() => {});
  }

  try {
    await page.goto('https://shopee.com.br/', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await pause([5000, 8000]);
    await checkSession(page);
    for (const query of expandQueries(config, args.only)) {
      if (!collector.searchesLeft) {
        log.erros.push({ erro: `teto de ${config.teto_buscas} buscas; consultas restantes ficaram para amanhã` });
        break;
      }
      await collector.runQuery(query);
      await checkSession(page);
    }
    await collector.resolveUnknownLeaves();
    if (args.pdp && config.pdp?.ativo !== false) await collector.enrich(config.pdp?.max_itens ?? 250);
    if (!collector.rows.size) throw new StopRun('nenhum livro coletado', EXIT.failure);
  } catch (error) {
    exitCode = error instanceof StopRun ? error.exitCode : EXIT.failure;
    log.erros.push({ erro: error.message });
    console.error('Parou:', error.message);
    if (exitCode !== EXIT.ok) await notify(`${error.message}. Parcial salvo em out/ (não importado).`);
  }
  await finish(exitCode);
  console.log(`${collector.rows.size} livros · modo ${collector.mode} · ${collector.requests} buscas · exit ${exitCode}`);
  process.exit(exitCode);
}

main().catch(async (error) => {
  console.error(error);
  await notify(`falhou: ${error.message}`);
  process.exit(EXIT.failure);
});
