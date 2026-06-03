<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import {
  getArticle,
  getArticles,
  getEntities,
  getGithubTop,
  getHuggingFaceTop,
  getProjectAdvice,
  getStats,
  getWeeklyEmergingTopics,
  getWeeklyTopics,
} from "./api";

const stats = ref({
  total: 0,
  sources: [],
  categories: [],
  latest_created: "",
});
const articles = ref([]);
const entities = ref([]);
const weeklyTopics = ref([]);
const weeklyEmergingTopics = ref([]);
const githubTop = ref([]);
const huggingFaceTop = ref([]);
const projectQuery = ref("");
const projectAdvice = ref(null);
const selectedArticle = ref(null);
const loading = ref(true);
const detailLoading = ref(false);
const projectLoading = ref(false);
const error = ref("");
const projectError = ref("");

const filters = reactive({
  source: "",
  category: "",
  query: "",
});

let searchTimer = null;

const activeSourceLabel = computed(() => filters.source || "All sources");
const activeCategoryLabel = computed(() => filters.category || "All categories");
const topEntities = computed(() => entities.value.slice(0, 8));

function plainPreview(text) {
  return String(text || "")
    .replace(/^#{1,4}\s*/gm, "")
    .replace(/\*\*/g, "")
    .trim();
}

function summaryBlocks(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  const blocks = [];

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;

    if (line.startsWith("### ")) {
      blocks.push({ type: "heading", text: line.slice(4) });
    } else if (line.startsWith("- ")) {
      blocks.push({ type: "bullet", text: line.slice(2) });
    } else {
      blocks.push({ type: "paragraph", text: line });
    }
  }

  return blocks;
}

function formatTrendScore(value) {
  const score = Number(value || 0);
  return score ? score.toFixed(1) : "0";
}

function trendComponentEntries(components) {
  const labels = {
    relevance: "Relevance",
    importance: "Importance",
    source: "Source",
    entity: "Entity",
    recency: "Recency",
  };
  return Object.entries(components || {}).map(([key, value]) => ({
    key,
    label: labels[key] || key,
    value: Number(value || 0).toFixed(1),
  }));
}

function entityTypeLabel(type) {
  const labels = {
    tool: "Tool",
    company: "Company",
    model: "Model",
    framework: "Framework",
    product: "Product",
    other: "Other",
  };
  return labels[type] || "Other";
}

function topicTypeLabel(type) {
  if (type === "category") return "Category";
  return entityTypeLabel(type);
}

function formatPlatformMetric(value) {
  const number = Number(value || 0);
  return new Intl.NumberFormat("en-US", { notation: "compact" }).format(number);
}

function analysisList(value) {
  return Array.isArray(value) ? value.filter(Boolean).slice(0, 3) : [];
}

function sourceTypeLabel(type) {
  const labels = {
    github: "GitHub",
    huggingface: "Hugging Face",
    research: "Research",
    web: "Web",
  };
  return labels[type] || type || "Source";
}

async function loadStats() {
  stats.value = await getStats();
}

async function loadEntities() {
  entities.value = await getEntities();
}

async function loadWeeklyTopics() {
  weeklyTopics.value = await getWeeklyTopics();
}

async function loadWeeklyEmergingTopics() {
  weeklyEmergingTopics.value = await getWeeklyEmergingTopics();
}

async function loadPlatformRankings() {
  const [github, huggingFace] = await Promise.all([
    getGithubTop(10),
    getHuggingFaceTop(10),
  ]);
  githubTop.value = github;
  huggingFaceTop.value = huggingFace;
}

async function loadArticles() {
  loading.value = true;
  error.value = "";
  try {
    articles.value = await getArticles(filters);
    if (articles.value.length) {
      const stillVisible = articles.value.some((article) => {
        return selectedArticle.value && article.id === selectedArticle.value.id;
      });
      if (!stillVisible) {
        await selectArticle(articles.value[0].id);
      }
    } else {
      selectedArticle.value = null;
    }
  } catch (err) {
    error.value = "Failed to load articles. Check the Python API server.";
  } finally {
    loading.value = false;
  }
}

async function analyzeProject() {
  const query = projectQuery.value.trim();
  if (!query) return;

  projectLoading.value = true;
  projectError.value = "";
  try {
    projectAdvice.value = await getProjectAdvice(query);
  } catch (err) {
    projectError.value = "Project analysis failed. Check API keys and backend logs.";
  } finally {
    projectLoading.value = false;
  }
}

async function selectArticle(id) {
  detailLoading.value = true;
  try {
    selectedArticle.value = await getArticle(id);
  } finally {
    detailLoading.value = false;
  }
}

function setSource(source) {
  filters.source = filters.source === source ? "" : source;
}

function setCategory(category) {
  filters.category = filters.category === category ? "" : category;
}

watch(
  () => [filters.source, filters.category],
  () => loadArticles()
);

watch(
  () => filters.query,
  () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadArticles(), 180);
  }
);

onMounted(async () => {
  await loadStats();
  await loadEntities();
  await loadWeeklyTopics();
  await loadWeeklyEmergingTopics();
  await loadPlatformRankings();
  await loadArticles();
});
</script>

<template>
  <main class="app-shell">
    <header class="hero">
      <div class="hero-copy">
        <p class="eyebrow">AI Trend Desk</p>
        <h1>AI Trend Radar</h1>
        <p class="hero-subtitle">AI trend dashboard with RSS, APIs, rankings, and AI analysis.</p>
      </div>
      <div class="hero-status">
        <span>{{ stats.total }} articles</span>
        <span>Latest {{ stats.latest_created || "No data" }}</span>
      </div>
    </header>

    <section class="metrics" aria-label="metrics">
      <div class="metric">
        <span>Total articles</span>
        <strong>{{ stats.total }}</strong>
      </div>
      <div class="metric">
        <span>Sources</span>
        <strong>{{ stats.sources.length }}</strong>
      </div>
      <div class="metric">
        <span>Categories</span>
        <strong>{{ stats.categories.length }}</strong>
      </div>
      <div class="metric metric-wide">
        <span>Active filters</span>
        <strong>{{ activeSourceLabel }} / {{ activeCategoryLabel }}</strong>
      </div>
    </section>

    <section class="project-advisor" aria-label="project advisor">
      <div class="panel-heading advisor-heading">
        <div>
          <p class="eyebrow">Project Advisor</p>
          <h2>Project Advisor</h2>
        </div>
        <span>GitHub / Hugging Face / Research / Web</span>
      </div>
      <form class="advisor-form" @submit.prevent="analyzeProject">
        <input
          v-model="projectQuery"
          type="search"
          placeholder="Describe a project idea, tool, model, or unknown AI term"
        />
        <button type="submit" :disabled="projectLoading || !projectQuery.trim()">
          {{ projectLoading ? "Analyzing..." : "Analyze" }}
        </button>
      </form>

      <p v-if="projectError" class="notice">{{ projectError }}</p>
      <div v-if="projectAdvice" class="advisor-result">
        <section>
          <h3>Project summary</h3>
          <p>{{ projectAdvice.project_nature }}</p>
        </section>

        <section>
          <h3>GitHub projects</h3>
          <p v-if="!projectAdvice.github_projects?.length" class="muted-note">No matching GitHub projects found.</p>
          <div v-else class="advisor-cards">
            <article v-for="project in projectAdvice.github_projects" :key="project.url">
              <a :href="project.url" target="_blank" rel="noreferrer">{{ project.name }}</a>
              <p>{{ project.why_relevant }}</p>
              <span>{{ project.language || "unknown" }} ? {{ formatPlatformMetric(project.stars) }} stars</span>
            </article>
          </div>
        </section>

        <section>
          <h3>Hugging Face models</h3>
          <p v-if="!projectAdvice.huggingface_models?.length" class="muted-note">No matching Hugging Face models found.</p>
          <div v-else class="advisor-cards">
            <article v-for="model in projectAdvice.huggingface_models" :key="model.url">
              <a :href="model.url" target="_blank" rel="noreferrer">{{ model.name }}</a>
              <p>{{ model.why_relevant }}</p>
              <span>{{ model.task || "model" }} ? {{ formatPlatformMetric(model.downloads) }} downloads</span>
            </article>
          </div>
        </section>

        <section>
          <h3>Research directions</h3>
          <div class="research-list">
            <a
              v-for="direction in projectAdvice.research_directions"
              :key="direction.url || direction.title"
              :href="direction.url"
              target="_blank"
              rel="noreferrer"
            >
              <strong>{{ direction.title }}</strong>
              <span>{{ direction.why_relevant }}</span>
            </a>
          </div>
        </section>

        <section>
          <h3>Sources</h3>
          <div class="source-list">
            <a
              v-for="source in projectAdvice.sources"
              :key="source.url || source.title"
              :href="source.url"
              target="_blank"
              rel="noreferrer"
            >
              {{ sourceTypeLabel(source.source_type) }} ? {{ source.title }}
            </a>
          </div>
        </section>
      </div>
    </section>

    <section class="weekly-topics" aria-label="weekly topics">
      <div class="panel-heading weekly-heading">
        <div>
          <p class="eyebrow">Weekly Signals</p>
          <h2>Weekly Discussion Top 5</h2>
        </div>
        <span>last 7 days</span>
      </div>

      <p v-if="!weeklyTopics.length" class="notice">No weekly topic data yet.</p>
      <div v-else class="topic-chart">
        <article v-for="(topic, index) in weeklyTopics" :key="`${topic.topic_type}-${topic.name}`" class="topic-bar">
          <div class="topic-rank">{{ index + 1 }}</div>
          <div class="topic-main">
            <div class="topic-line">
              <div>
                <h3>{{ topic.name }}</h3>
                <p>
                  {{ topicTypeLabel(topic.topic_type) }} ? {{ topic.article_count }} articles ?
                  {{ topic.source_count }} sources
                </p>
              </div>
              <strong>{{ Number(topic.discussion_score || 0).toFixed(1) }}</strong>
            </div>
            <div class="bar-track" aria-hidden="true">
              <span :style="{ width: `${Math.max(topic.share || 0, 4)}%` }"></span>
            </div>
            <div class="topic-sources">
              <span v-for="source in topic.sources.slice(0, 4)" :key="source">{{ source }}</span>
            </div>
          </div>
        </article>
      </div>
    </section>

    <section class="emerging-topics" aria-label="emerging signals">
      <div class="panel-heading weekly-heading">
        <div>
          <p class="eyebrow">Emerging Signals</p>
          <h2>Emerging Signals Top 5</h2>
        </div>
        <span>last 7 days</span>
      </div>

      <p v-if="!weeklyEmergingTopics.length" class="notice">No emerging signal data yet.</p>
      <div v-else class="emerging-list">
        <article v-for="(topic, index) in weeklyEmergingTopics" :key="topic.id" class="emerging-item">
          <div class="topic-rank">{{ index + 1 }}</div>
          <div class="emerging-main">
            <h3>{{ topic.term }}</h3>
            <div class="emerging-metrics">
              <span>{{ topic.mention_count }} mentions</span>
              <span>{{ topic.source_count }} sources</span>
              <span>{{ topic.article_count }} articles</span>
              <span>Trend score {{ Number(topic.trend_score_sum || 0).toFixed(1) }}</span>
            </div>
          </div>
          <strong>{{ Number(topic.weekly_signal_score || 0).toFixed(1) }}</strong>
        </article>
      </div>
    </section>

    <section class="platform-rankings" aria-label="platform rankings">
      <div class="platform-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">GitHub</p>
            <h2>GitHub Stars Top 10</h2>
          </div>
          <span>stars</span>
        </div>
        <p v-if="!githubTop.length" class="notice">No GitHub ranking data yet.</p>
        <ol v-else class="ranking-list">
          <li v-for="item in githubTop" :key="item.item_id">
            <span class="ranking-index">{{ item.rank }}</span>
            <div class="ranking-main">
              <a :href="item.url" target="_blank" rel="noreferrer">{{ item.name }}</a>
              <p>{{ item.description || "No description" }}</p>
              <div class="ranking-tags">
                <span v-if="item.category">{{ item.category }}</span>
                <span v-for="tag in item.tags.slice(0, 3)" :key="tag">{{ tag }}</span>
              </div>
              <details v-if="item.ai_summary || item.quickstart" class="ranking-analysis">
                <summary>AI analysis</summary>
                <div class="ranking-analysis-body">
                  <p v-if="item.ai_summary">{{ item.ai_summary }}</p>
                  <div v-if="analysisList(item.ai_analysis?.main_uses).length" class="analysis-row">
                    <span>Uses</span>
                    <ul>
                      <li v-for="use in analysisList(item.ai_analysis.main_uses)" :key="use">{{ use }}</li>
                    </ul>
                  </div>
                  <div v-if="item.quickstart" class="analysis-row">
                    <span>Start</span>
                    <p>{{ item.quickstart }}</p>
                  </div>
                  <div v-if="item.popularity_reason" class="analysis-row">
                    <span>Why popular</span>
                    <p>{{ item.popularity_reason }}</p>
                  </div>
                </div>
              </details>
            </div>
            <strong class="ranking-metric">{{ formatPlatformMetric(item.primary_metric_value) }}</strong>
          </li>
        </ol>
      </div>

      <div class="platform-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Hugging Face</p>
            <h2>Hugging Face Downloads Top 10</h2>
          </div>
          <span>downloads</span>
        </div>
        <p v-if="!huggingFaceTop.length" class="notice">No Hugging Face ranking data yet.</p>
        <ol v-else class="ranking-list">
          <li v-for="item in huggingFaceTop" :key="item.item_id">
            <span class="ranking-index">{{ item.rank }}</span>
            <div class="ranking-main">
              <a :href="item.url" target="_blank" rel="noreferrer">{{ item.name }}</a>
              <p>{{ item.category || "model" }}</p>
              <div class="ranking-tags">
                <span v-for="tag in item.tags.slice(0, 4)" :key="tag">{{ tag }}</span>
              </div>
              <details v-if="item.ai_summary || item.quickstart" class="ranking-analysis">
                <summary>AI analysis</summary>
                <div class="ranking-analysis-body">
                  <p v-if="item.ai_summary">{{ item.ai_summary }}</p>
                  <div v-if="analysisList(item.ai_analysis?.main_uses).length" class="analysis-row">
                    <span>Uses</span>
                    <ul>
                      <li v-for="use in analysisList(item.ai_analysis.main_uses)" :key="use">{{ use }}</li>
                    </ul>
                  </div>
                  <div v-if="item.quickstart" class="analysis-row">
                    <span>Start</span>
                    <p>{{ item.quickstart }}</p>
                  </div>
                  <div v-if="item.popularity_reason" class="analysis-row">
                    <span>Why popular</span>
                    <p>{{ item.popularity_reason }}</p>
                  </div>
                </div>
              </details>
            </div>
            <strong class="ranking-metric">{{ formatPlatformMetric(item.primary_metric_value) }}</strong>
          </li>
        </ol>
      </div>
    </section>

    <section class="workspace">
      <aside class="filters-panel" aria-label="filters">
        <label class="search-label" for="article-search">Search</label>
        <input
          id="article-search"
          v-model="filters.query"
          class="search-input"
          type="search"
          placeholder="Search articles, sources, or entities"
        />

        <div class="filter-section">
          <p>Top entities</p>
          <div v-if="topEntities.length" class="entity-list">
            <span v-for="entity in topEntities" :key="entity.id" class="entity-pill">
              {{ entity.canonical_name }}
              <small>{{ entityTypeLabel(entity.entity_type) }} 蝜?{{ entity.mention_count }}</small>
            </span>
          </div>
          <p v-else class="muted-note">No entity data yet.</p>
        </div>

        <div class="filter-section">
          <p>Sources</p>
          <button
            class="chip"
            :class="{ active: !filters.source }"
            type="button"
            @click="filters.source = ''"
          >
            ??賂?
          </button>
          <button
            v-for="source in stats.sources"
            :key="source.source"
            class="chip"
            :class="{ active: filters.source === source.source }"
            type="button"
            @click="setSource(source.source)"
          >
            {{ source.source }} <span>{{ source.count }}</span>
          </button>
        </div>

        <div class="filter-section">
          <p>Categories</p>
          <button
            class="chip"
            :class="{ active: !filters.category }"
            type="button"
            @click="filters.category = ''"
          >
            ??賂?
          </button>
          <button
            v-for="category in stats.categories"
            :key="category.category"
            class="chip"
            :class="{ active: filters.category === category.category }"
            type="button"
            @click="setCategory(category.category)"
          >
            {{ category.category }} <span>{{ category.count }}</span>
          </button>
        </div>
      </aside>

      <section class="feed-panel" aria-label="article list">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Inbox</p>
            <h2>Articles</h2>
          </div>
          <span>{{ articles.length }} items</span>
        </div>

        <p v-if="error" class="notice">{{ error }}</p>
        <p v-else-if="loading" class="notice">??謘??∵???..</p>
        <p v-else-if="!articles.length" class="notice">No articles match the current filters.</p>

        <div v-else class="article-list">
          <button
            v-for="article in articles"
            :key="article.id"
            class="article-card"
            :class="{ active: selectedArticle?.id === article.id }"
            type="button"
            @click="selectArticle(article.id)"
          >
            <div class="card-topline">
              <span class="source">{{ article.source }}</span>
              <span class="score-badge">???{{ formatTrendScore(article.trend_score) }}</span>
            </div>
            <h3>{{ article.title }}</h3>
            <p>{{ plainPreview(article.preview) }}</p>
            <div v-if="article.entities?.length" class="entity-row">
              <span v-for="entity in article.entities.slice(0, 3)" :key="entity.id">
                {{ entity.canonical_name }}
              </span>
            </div>
            <div class="card-footer">
              <span>{{ article.category }}</span>
              <span>{{ article.published || article.created_at }}</span>
            </div>
          </button>
        </div>
      </section>

      <section class="detail-panel" aria-label="????謢?">
        <div v-if="detailLoading" class="empty-detail">??謘??秋撩??..</div>
        <div v-else-if="!selectedArticle" class="empty-detail">Select an article to view details</div>
        <article v-else class="article-detail">
          <div class="detail-meta">
            <span>{{ selectedArticle.source }}</span>
            <span>{{ selectedArticle.category }}</span>
            <span>{{ selectedArticle.published || selectedArticle.created_at }}</span>
          </div>
          <h2>{{ selectedArticle.title }}</h2>
          <a :href="selectedArticle.link" target="_blank" rel="noreferrer">????賹?</a>

          <section class="trend-box" aria-label="????">
            <div>
              <span>Trend score</span>
              <strong>{{ formatTrendScore(selectedArticle.trend_score) }}</strong>
            </div>
            <p>{{ selectedArticle.trend_reason || "No trend score explanation yet" }}</p>
            <div class="component-grid">
              <span
                v-for="component in trendComponentEntries(selectedArticle.trend_components)"
                :key="component.key"
              >
                {{ component.label }} <strong>{{ component.value }}</strong>
              </span>
            </div>
          </section>

          <section v-if="selectedArticle.entities?.length" class="detail-entities" aria-label="?鞈???">
            <h3>Entities</h3>
            <div class="entity-list">
              <span v-for="entity in selectedArticle.entities" :key="entity.id" class="entity-pill">
                {{ entity.canonical_name }}
                <small>{{ entityTypeLabel(entity.entity_type) }}</small>
              </span>
            </div>
          </section>

          <div class="summary">
            <template
              v-for="(block, index) in summaryBlocks(selectedArticle.ai_summary || selectedArticle.summary)"
              :key="index"
            >
              <h3 v-if="block.type === 'heading'">{{ block.text }}</h3>
              <p v-else-if="block.type === 'paragraph'">{{ block.text }}</p>
              <ul v-else>
                <li>{{ block.text }}</li>
              </ul>
            </template>
          </div>
        </article>
      </section>
    </section>
  </main>
</template>
