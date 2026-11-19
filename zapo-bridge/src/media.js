import sharp from 'sharp';
import { InvalidInputError } from './errors.js';

const DOWNLOAD_TIMEOUT_MS = 20_000;
const BASE64_PATTERN = /^[A-Za-z0-9+/]+={0,2}$/;

// Normaliza a imagem para JPEG e devolve as dimensões reais; sem elas o
// WhatsApp mostra a prévia com proporção errada até o download.
export async function loadImage(file, { maxBytes, fetchImpl = fetch }) {
  const raw = await readSource(file, maxBytes, fetchImpl);
  let image;
  try {
    image = sharp(raw, { failOn: 'error' }).rotate();
    const metadata = await image.metadata();
    if (!metadata.width || !metadata.height) throw new Error('sem dimensões');
    const bytes = metadata.format === 'jpeg' && !metadata.orientation
      ? raw
      : await image.jpeg({ quality: 90 }).toBuffer();
    const portrait = metadata.orientation >= 5;
    return {
      bytes: new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength),
      width: portrait ? metadata.height : metadata.width,
      height: portrait ? metadata.width : metadata.height,
    };
  } catch (error) {
    if (error instanceof InvalidInputError) throw error;
    throw new InvalidInputError(`Imagem ilegível: ${error.message}`);
  }
}

async function readSource(file, maxBytes, fetchImpl) {
  if (!file || typeof file !== 'object' || Array.isArray(file)) {
    throw new InvalidInputError('file é obrigatório.');
  }
  if (typeof file.data === 'string' && file.data) {
    const compact = file.data.replace(/\s+/g, '');
    if (!BASE64_PATTERN.test(compact)) throw new InvalidInputError('file.data não é base64.');
    const bytes = Buffer.from(compact, 'base64');
    assertSize(bytes.byteLength, maxBytes);
    return bytes;
  }
  if (typeof file.url === 'string' && file.url) {
    return download(file.url, maxBytes, fetchImpl);
  }
  throw new InvalidInputError('Informe file.url ou file.data.');
}

async function download(url, maxBytes, fetchImpl) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    throw new InvalidInputError('file.url inválida.');
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    throw new InvalidInputError('file.url precisa ser http ou https.');
  }

  let response;
  try {
    response = await fetchImpl(parsed, { signal: AbortSignal.timeout(DOWNLOAD_TIMEOUT_MS) });
  } catch (error) {
    throw new InvalidInputError(`Não consegui baixar a imagem: ${error.message}`);
  }
  if (!response.ok) throw new InvalidInputError(`Download da imagem falhou: HTTP ${response.status}.`);
  const declared = Number(response.headers.get('content-length'));
  if (Number.isFinite(declared)) assertSize(declared, maxBytes);
  const bytes = Buffer.from(await response.arrayBuffer());
  assertSize(bytes.byteLength, maxBytes);
  return bytes;
}

function assertSize(size, maxBytes) {
  if (size === 0) throw new InvalidInputError('Imagem vazia.');
  if (size > maxBytes) throw new InvalidInputError('Imagem grande demais.');
}
