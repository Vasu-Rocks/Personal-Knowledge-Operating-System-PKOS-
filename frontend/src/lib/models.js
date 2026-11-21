// Ollama models offered in the setup wizard and Settings. Any other Ollama model name can be typed in too.
export const RECOMMENDED_MODELS = [
  {
    name: 'llama3.2',
    title: 'Llama 3.2 (3B)',
    size: '2.0 GB',
    ram: '8 GB RAM',
    note: 'Recommended. Good answers and knowledge-graph extraction on most laptops.',
  },
  {
    name: 'llama3.2:1b',
    title: 'Llama 3.2 (1B)',
    size: '1.3 GB',
    ram: '4 GB RAM',
    note: 'Fastest and smallest. Weaker answers; for low-memory PCs.',
  },
  {
    name: 'llama3.1:8b',
    title: 'Llama 3.1 (8B)',
    size: '4.9 GB',
    ram: '16 GB RAM',
    note: 'Better answers, slower. Best with a GPU that has 6 GB or more.',
  },
];

export const CLOUD_PROVIDERS = {
  openai: { label: 'OpenAI', keyPlaceholder: 'sk-...', defaultModel: 'gpt-4o-mini', keyUrl: 'https://platform.openai.com/api-keys' },
  anthropic: { label: 'Anthropic', keyPlaceholder: 'sk-ant-...', defaultModel: 'claude-haiku-5-5', keyUrl: 'https://console.anthropic.com/settings/keys' },
};

/** 'llama3.2' is installed as 'llama3.2:latest'. */
export function isInstalled(model, installed = []) {
  const withTag = model.includes(':') ? model : `${model}:latest`;
  return installed.includes(model) || installed.includes(withTag);
}

export function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}
