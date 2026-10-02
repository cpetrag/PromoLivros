export class LinkError extends Error {
  constructor(code, message, status = 400) {
    super(message);
    this.name = 'LinkError';
    this.code = code;
    this.status = status;
  }
}

export class ConfigError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ConfigError';
  }
}
