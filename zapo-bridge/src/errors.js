export class BridgeError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

// O WahaClient do Python lê "not working" + HTTP 422 como sessão caída e reagenda.
export class SessionNotWorkingError extends BridgeError {
  constructor() {
    super('Session status is not working. Scan QR code or wait.', 422, 'SESSION_NOT_WORKING');
  }
}

export class InvalidInputError extends BridgeError {
  constructor(message) {
    super(message, 400, 'ENTRADA_INVALIDA');
  }
}

export class NotFoundError extends BridgeError {
  constructor(message) {
    super(message, 404, 'NAO_ENCONTRADO');
  }
}
