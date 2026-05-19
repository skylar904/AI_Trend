const API_BASE = import.meta.env.VITE_API_BASE || "";

async function request(path) {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

export function getStats() {
  return request("/api/stats");
}

export function getArticles(filters) {
  const params = new URLSearchParams();
  if (filters.source) params.set("source", filters.source);
  if (filters.category) params.set("category", filters.category);
  if (filters.query) params.set("q", filters.query);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request(`/api/articles${suffix}`);
}

export function getArticle(id) {
  return request(`/api/articles/${id}`);
}
