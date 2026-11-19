// Regras puras do coletor: item da busca da Shopee -> linha do CSV. Sem rede, para dar para testar.

export const BOOKS_CATID = 100777;
export const BOOKS_FACET = '11060034';
export const PRICE_SCALE = 100000;

// Folha global da categoria -> { nome, facet }. Validado em 03/11/2026.
export const CATEGORIES = {
  101540: { name: "HQ's e Mangás", facet: '11060458' },
  101541: { name: 'Livros Infantis', facet: '11111986' },
  101544: { name: 'Artes, Design e Fotografia', facet: '11060451' },
  101546: { name: 'Negócios e Investimentos', facet: '11060455' },
  101547: { name: 'Políticas, Direito e Ciências Sociais', facet: '11060473' },
  101548: { name: 'Computadores e Tecnologia', facet: '11060459' },
  101552: { name: 'Hobbies', facet: '11060464' },
  101555: { name: 'Literatura Clássica', facet: '11060457' },
  101556: { name: 'Ficção', facet: '11060461' },
  101557: { name: 'Ação, Crime e Suspense', facet: '11060448' },
  101558: { name: 'Romance', facet: '11060477' },
  101559: { name: 'Biografias e Memórias', facet: '11060454' },
  101560: { name: 'Ciência e Matemática', facet: '11060478' },
  101563: { name: 'Psicologia e Relações Pessoais', facet: '11060474' },
  101564: { name: 'Religião e Filosofia', facet: '11060476' },
  101565: { name: 'História e Culturas', facet: '11060463' },
  101566: { name: 'Carreiras, Autoajuda e Desenvolvimento Pessoal', facet: '11060456' },
  101568: { name: 'Educação e Escola', facet: '11060460' },
  101569: { name: 'Adesivos e Livros para Colorir', facet: '11060479' },
  101571: { name: 'Livros Para Bebês', facet: '11060453' },
  101573: { name: 'Outros', facet: '11060471' },
};

export const COLUMNS = [
  'posicao', 'asin', 'titulo', 'preco', 'preco_de', 'link', 'imagem', 'menor_preco_365', 'categoria',
  'categoria_caminho', 'autor', 'nota', 'avaliacoes', 'vendidos', 'cupom', 'loja_nome', 'loja_oficial',
  'frete_gratis', 'esgotado', 'preco_min', 'preco_max',
  // Extras: o importador do painel ignora coluna que não conhece.
  'preco_pix', 'desconto_pct', 'isbn', 'editora', 'full', 'vendidos_mes', 'origem', 'coletado_em',
];

const EDITION_WORDS = /\b(capa|edi[cç][aã]o|volume|vol\.?|box|kit|livro|livros|cole[cç][aã]o|luxo|dura|mole|brochura|completo|especial)\b/i;
const AUTHOR_PATTERNS = [/\s[-–]\s([^-–|]+)$/, /\|\s*([^|]+)$/, /\spor\s(.+)$/i, /\sde\s(.+)$/i];

export function brl(value) {
  const cents = Math.round(Number(value) / (PRICE_SCALE / 100));
  if (!Number.isFinite(cents) || cents <= 0) return '';
  return 'R$ ' + (cents / 100).toFixed(2).replace('.', ',');
}

export function clean(text) {
  return String(text ?? '').replace(/[\r\n]+/g, ' ').replace(/;/g, ',').replace(/\s+/g, ' ').trim();
}

export function digits(value) {
  const number = Math.trunc(Number(value));
  return Number.isFinite(number) && number > 0 ? String(number) : '';
}

/** "1,2mil+ Vendido(s)" -> 1200; "10mil+" -> 10000; "87 vendidos" -> 87. */
export function parseSoldText(text) {
  const match = String(text ?? '').toLowerCase().replace(/\s/g, '').match(/(\d+(?:[.,]\d+)?)(mil|k)?/);
  if (!match) return '';
  const base = Number(match[1].replace(',', '.'));
  if (!Number.isFinite(base)) return '';
  return digits(match[2] ? base * 1000 : base);
}

/** Autor só quando o título deixa claro. Na dúvida, vazio: autor errado atrapalha o casamento com a Amazon. */
export function guessAuthor(title) {
  const text = String(title ?? '').trim();
  for (const pattern of AUTHOR_PATTERNS) {
    const found = text.match(pattern);
    if (!found) continue;
    const name = found[1].trim();
    const words = name.split(/\s+/);
    if (words.length < 2 || words.length > 4 || /\d/.test(name) || EDITION_WORDS.test(name)) continue;
    const connectors = new Set(['de', 'da', 'do', 'dos', 'das', 'e']);
    if (words.every((word) => connectors.has(word.toLowerCase()) || /^[A-ZÀ-Ý][\p{L}.'’-]*$/u.test(word))) return name;
  }
  return '';
}

export function categoryOf(catids, categories = CATEGORIES) {
  const path = Array.isArray(catids) ? catids : [];
  if (path[1] !== BOOKS_CATID) return { book: false, leaf: path.at(-1) ?? null, name: '' };
  const leaf = path.at(-1);
  const name = categories[leaf]?.name ?? '';
  return { book: true, leaf, name };
}

/**
 * Item de /search/search_items -> { row } ou { skip: motivo }.
 * `unknownLeaf` vem preenchido quando a folha não está no mapa (o chamador resolve pela PDP).
 */
export function mapItem(item, { categories = CATEGORIES, origin = '', collectedAt = '' } = {}) {
  const data = item?.item_data;
  const asset = item?.item_card_displayed_asset ?? {};
  if (!data || item.adsid) return { skip: 'anuncio_ou_sem_dados' };
  const category = categoryOf(data.global_cat?.catid, categories);
  if (!category.book) return { skip: 'nao_livro' };
  if (data.is_sold_out) return { skip: 'esgotado' };
  if (data.is_adult) return { skip: 'adulto' };
  const shopId = data.shopid ?? item.shopid;
  const itemId = data.itemid ?? item.itemid;
  const price = data.item_card_display_price ?? {};
  const current = price.applied_product_promo_price || price.price;
  const preco = brl(current);
  const title = clean(asset.name);
  const image = asset.image ? `https://down-br.img.susercontent.com/file/${asset.image}` : '';
  if (!shopId || !itemId || !title || !preco || !image) return { skip: 'falta_obrigatorio' };
  const strike = Number(price.strikethrough_price) > Number(current) ? price.strikethrough_price : null;
  const rating = data.item_rating ?? {};
  const reviews = Array.isArray(rating.rating_count) ? Number(rating.rating_count[0]) || 0 : 0;
  const sold = data.item_card_display_sold_count ?? {};
  const row = {
    posicao: '',
    asin: `${shopId}.${itemId}`,
    titulo: title,
    preco,
    preco_de: strike ? brl(strike) : '',
    link: `https://shopee.com.br/product/${shopId}/${itemId}`,
    imagem: image,
    menor_preco_365: '',
    categoria: category.name,
    categoria_caminho: category.name ? `Livros e Revistas > Livros > ${category.name}` : '',
    autor: guessAuthor(title),
    nota: reviews && Number(rating.rating_star) > 0 ? Number(rating.rating_star).toFixed(1) : '',
    avaliacoes: reviews ? String(reviews) : '',
    vendidos: digits(sold.historical_sold_count) || parseSoldText(sold.historical_sold_count_text),
    cupom: '',
    loja_nome: clean(data.shop_data?.shop_name),
    loja_oficial: asset.seller_flag?.name === 'OFFICIAL_SHOP' ? 'sim' : 'não',
    frete_gratis: '',
    esgotado: 'não',
    preco_min: '',
    preco_max: '',
    preco_pix: price.pix_discount_info && price.price && price.price !== current ? brl(price.price) : '',
    desconto_pct: strike ? String(Math.round((1 - Number(current) / Number(strike)) * 100)) : '',
    isbn: '',
    editora: clean(data.global_brand?.display_name),
    full: (asset.in_title_image_flags ?? []).some((flag) => flag?.name === 'FBS_LOGO') ? 'sim' : 'não',
    vendidos_mes: digits(sold.monthly_sold_count),
    origem: origin,
    coletado_em: collectedAt,
  };
  return { row, unknownLeaf: category.name ? null : category.leaf, rawPrice: Number(current) };
}

/** Só preenche o que está vazio: a primeira consulta que achou o item manda. */
export function mergeRow(target, extra) {
  for (const [key, value] of Object.entries(extra)) {
    if ((target[key] === '' || target[key] === undefined) && value !== '' && value !== undefined) target[key] = value;
  }
  return target;
}

const ATTRIBUTE_IDS = { isbn: 100697, publisher: 100669, distributor: 101294 };

/** Resposta de /pdp/get_pc -> campos extras da linha. `unavailable` tira o item do CSV. */
export function pdpExtras(payload, currentPrice) {
  const data = payload?.data ?? {};
  const item = data.item ?? {};
  const attributes = Array.isArray(item.attributes) ? item.attributes : [];
  const attribute = (id) => clean(attributes.find((entry) => Number(entry?.id) === id)?.value);
  const isbn = attribute(ATTRIBUTE_IDS.isbn).replace(/[^0-9Xx]/g, '').toUpperCase();
  const range = data.product_price?.price ?? {};
  const min = Number(range.range_min);
  const max = Number(range.range_max);
  const shipping = data.product_shipping?.free_shipping;
  const minSpend = Number(shipping?.min_spend);
  const vouchers = Array.isArray(data.shop_vouchers) ? data.shop_vouchers : [];
  return {
    unavailable: Boolean(item.is_unavailable),
    leafName: leafNameFromPdp(item),
    row: {
      isbn: /^(\d{9}[\dX]|\d{13})$/.test(isbn) ? isbn : '',
      editora: attribute(ATTRIBUTE_IDS.publisher) || attribute(ATTRIBUTE_IDS.distributor),
      preco_min: min > 0 && max > 0 && max / min > 1.15 ? brl(min) : '',
      preco_max: min > 0 && max > 0 && max / min > 1.15 ? brl(max) : '',
      frete_gratis: shipping ? (shipping.has_fss || (minSpend >= 0 && minSpend <= currentPrice) ? 'sim' : 'não') : '',
      cupom: voucherText(vouchers[0]),
      loja_oficial: data.shop_detailed?.is_official_shop ? 'sim' : '',
    },
  };
}

function leafNameFromPdp(item) {
  const categories = Array.isArray(item.categories) ? item.categories : [];
  return clean(categories.at(-1)?.display_name);
}

function voucherText(voucher) {
  if (!voucher) return '';
  const minimum = Number(voucher.min_spend) > 0 ? ` acima de ${brl(voucher.min_spend)}` : '';
  if (Number(voucher.discount_value) > 0) return `${brl(voucher.discount_value)} OFF${minimum}`;
  if (Number(voucher.discount_percentage) > 0) return `${voucher.discount_percentage}% OFF${minimum}`;
  return clean(voucher.voucher_code);
}

function quote(value) {
  return `"${String(value ?? '').replace(/"/g, '""')}"`;
}

export function toCsv(rows) {
  const lines = [COLUMNS.map(quote).join(';')];
  for (const row of rows) lines.push(COLUMNS.map((column) => quote(row[column])).join(';'));
  return '\ufeff' + lines.join('\n') + '\n';
}

/** Ordem de PDP: maior desconto, depois mais vendidos. São os candidatos a post. */
export function pdpCandidates(rows, limit) {
  return [...rows]
    .sort((a, b) => (Number(b.desconto_pct) || 0) - (Number(a.desconto_pct) || 0) || (Number(b.vendidos) || 0) - (Number(a.vendidos) || 0))
    .slice(0, Math.max(0, limit));
}
