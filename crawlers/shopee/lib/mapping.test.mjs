import assert from 'node:assert/strict';
import test from 'node:test';

import { brl, guessAuthor, mapItem, mergeRow, parseSoldText, pdpCandidates, pdpExtras, toCsv } from './mapping.mjs';

function searchItem(overrides = {}) {
  return {
    itemid: 41158748466,
    shopid: 482840775,
    adsid: null,
    item_data: {
      itemid: 41158748466,
      shopid: 482840775,
      item_card_display_price: { price: 1841000, applied_product_promo_price: 1938000, strikethrough_price: 3990000, pix_discount_info: {} },
      item_card_display_sold_count: { historical_sold_count: 159275, monthly_sold_count: 3100 },
      item_rating: { rating_star: 4.96, rating_count: [88791, 1, 2, 3, 4, 5] },
      global_cat: { catid: [100643, 100777, 101564] },
      shop_data: { shop_name: 'Online Editora' },
      global_brand: { display_name: 'Online' },
      ...overrides.item_data,
    },
    item_card_displayed_asset: {
      name: 'Mulheres com Deus; 365 Dias de Fé',
      image: 'sg-11134201-7rdxz-mc9mb2wz7xjld0',
      seller_flag: { name: 'OFFICIAL_SHOP' },
      in_title_image_flags: [{ name: 'FBS_LOGO' }],
      ...overrides.asset,
    },
    ...overrides.item,
  };
}

test('maps a search item to the panel CSV row', () => {
  const { row, unknownLeaf } = mapItem(searchItem(), { origin: 'geral-vendas' });
  assert.equal(unknownLeaf, null);
  assert.equal(row.asin, '482840775.41158748466');
  assert.equal(row.link, 'https://shopee.com.br/product/482840775/41158748466');
  assert.equal(row.titulo, 'Mulheres com Deus, 365 Dias de Fé');
  assert.equal(row.preco, 'R$ 19,38');
  assert.equal(row.preco_de, 'R$ 39,90');
  assert.equal(row.preco_pix, 'R$ 18,41');
  assert.equal(row.desconto_pct, '51');
  assert.equal(row.categoria_caminho, 'Livros e Revistas > Livros > Religião e Filosofia');
  assert.equal(row.nota, '5.0');
  assert.equal(row.avaliacoes, '88791');
  assert.equal(row.vendidos, '159275');
  assert.equal(row.loja_oficial, 'sim');
  assert.equal(row.full, 'sim');
});

test('drops ads, non-books, sold out and adult items', () => {
  assert.equal(mapItem(searchItem({ item: { adsid: 123 } })).skip, 'anuncio_ou_sem_dados');
  assert.equal(mapItem(searchItem({ item_data: { global_cat: { catid: [100643, 100779] } } })).skip, 'nao_livro');
  assert.equal(mapItem(searchItem({ item_data: { is_sold_out: true } })).skip, 'esgotado');
  assert.equal(mapItem(searchItem({ item_data: { is_adult: true } })).skip, 'adulto');
  assert.equal(mapItem(searchItem({ asset: { image: '' } })).skip, 'falta_obrigatorio');
});

test('unknown leaf keeps the row and asks for the name', () => {
  const { row, unknownLeaf } = mapItem(searchItem({ item_data: { global_cat: { catid: [100643, 100777, 109999] } } }));
  assert.equal(unknownLeaf, 109999);
  assert.equal(row.categoria, '');
});

test('price and sold helpers', () => {
  assert.equal(brl(7729000), 'R$ 77,29');
  assert.equal(brl(0), '');
  assert.equal(parseSoldText('1,2mil+ Vendido(s)'), '1200');
  assert.equal(parseSoldText('10mil+'), '10000');
  assert.equal(parseSoldText('87 vendidos'), '87');
});

test('author only when the title is clear', () => {
  assert.equal(guessAuthor('O Príncipe - Nicolau Maquiavel'), 'Nicolau Maquiavel');
  assert.equal(guessAuthor('Romeu e Julieta | William Shakespeare'), 'William Shakespeare');
  assert.equal(guessAuthor('Biblioteca Nietzsche - Box com 4 Livros'), '');
  assert.equal(guessAuthor('O Livro dos Cinco Anéis - Miyamoto Musashi | Luxo Capa Dura'), '');
});

test('PDP extras fill only empty fields', () => {
  const extras = pdpExtras(
    {
      data: {
        item: { attributes: [{ id: 100697, value: '978-85-123-4567-8' }, { id: 100669, value: 'Principis' }], categories: [{ display_name: 'Livros' }, { display_name: 'Poesia' }] },
        product_price: { price: { range_min: 1000000, range_max: 3000000 } },
        product_shipping: { free_shipping: { has_fss: false, min_spend: 1000000 } },
        shop_vouchers: [{ discount_value: 1000000, min_spend: 8000000 }],
      },
    },
    1938000,
  );
  assert.equal(extras.unavailable, false);
  assert.equal(extras.leafName, 'Poesia');
  assert.equal(extras.row.isbn, '9788512345678');
  assert.equal(extras.row.preco_min, 'R$ 10,00');
  assert.equal(extras.row.frete_gratis, 'sim');
  assert.equal(extras.row.cupom, 'R$ 10,00 OFF acima de R$ 80,00');
  const row = mergeRow({ editora: 'Online', isbn: '' }, extras.row);
  assert.equal(row.editora, 'Online');
  assert.equal(row.isbn, '9788512345678');
});

test('CSV has BOM, quotes and doubled quotes', () => {
  const { row } = mapItem(searchItem({ asset: { name: 'O "corvo"' } }));
  const csv = toCsv([row]);
  assert.ok(csv.startsWith('\ufeff"posicao";"asin"'));
  assert.ok(csv.includes('"O ""corvo"""'));
});

test('PDP candidates by discount then sales', () => {
  const rows = [{ asin: 'a', desconto_pct: '10', vendidos: '5' }, { asin: 'b', desconto_pct: '50', vendidos: '1' }, { asin: 'c', desconto_pct: '50', vendidos: '9' }];
  assert.deepEqual(pdpCandidates(rows, 2).map((row) => row.asin), ['c', 'b']);
});
