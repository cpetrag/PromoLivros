export function createLog(write = console.log, writeError = console.error) {
  function emit(writer, level, event, fields = {}) {
    writer(JSON.stringify({
      ts: new Date().toISOString(),
      level,
      event,
      ...fields,
    }));
  }

  return {
    info(event, fields) {
      emit(write, 'info', event, fields);
    },
    error(event, fields) {
      emit(writeError, 'error', event, fields);
    },
  };
}

export const log = createLog();
export const silentLog = createLog(() => {}, () => {});
