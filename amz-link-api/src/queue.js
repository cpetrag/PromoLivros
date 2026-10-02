const defaultSleep = (ms) => new Promise((resolve) => {
  setTimeout(resolve, ms);
});

export function createQueue(minIntervalMs, { sleep = defaultSleep, now = Date.now } = {}) {
  let chain = Promise.resolve();
  let hasRun = false;
  let lastStartedAt = 0;

  function enqueue(task) {
    const run = chain.then(async () => {
      if (hasRun) {
        const waitMs = minIntervalMs - (now() - lastStartedAt);
        if (waitMs > 0) await sleep(waitMs);
      }
      lastStartedAt = now();
      hasRun = true;
      return task();
    });

    chain = run.then(() => undefined, () => undefined);
    return run;
  }

  return { enqueue };
}
