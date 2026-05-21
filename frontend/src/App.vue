<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { getArticle, getArticles, getEntities, getStats, getWeeklyTopics } from "./api";

const stats = ref({
  total: 0,
  sources: [],
  categories: [],
  latest_created: "",
});
const articles = ref([]);
const entities = ref([]);
const weeklyTopics = ref([]);
const selectedArticle = ref(null);
const loading = ref(true);
const detailLoading = ref(false);
const error = ref("");

const filters = reactive({
  source: "",
  category: "",
  query: "",
});

let searchTimer = null;

const activeSourceLabel = computed(() => filters.source || "全部來源");
const activeCategoryLabel = computed(() => filters.category || "全部分類");
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
    relevance: "相關性",
    importance: "重要性",
    source: "來源權重",
    entity: "實體訊號",
    recency: "近期性",
  };
  return Object.entries(components || {}).map(([key, value]) => ({
    key,
    label: labels[key] || key,
    value: Number(value || 0).toFixed(1),
  }));
}

function entityTypeLabel(type) {
  const labels = {
    tool: "工具",
    company: "公司",
    model: "模型",
    framework: "框架",
    product: "產品",
    other: "其他",
  };
  return labels[type] || "其他";
}

function topicTypeLabel(type) {
  if (type === "category") return "分類";
  return entityTypeLabel(type);
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
    error.value = "讀取文章失敗，請確認 Python API server 是否正在執行。";
  } finally {
    loading.value = false;
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
  await loadArticles();
});
</script>

<template>
  <main class="app-shell">
    <header class="hero">
      <div class="hero-copy">
        <p class="eyebrow">AI Trend Desk</p>
        <h1>AI 科技情報</h1>
        <p class="hero-subtitle">把 RSS、AI 摘要與追蹤建議整理成可掃描的情報工作台。</p>
      </div>
      <div class="hero-status">
        <span>{{ stats.total }} 篇文章</span>
        <span>更新 {{ stats.latest_created || "尚無資料" }}</span>
      </div>
    </header>

    <section class="metrics" aria-label="資料總覽">
      <div class="metric">
        <span>文章總數</span>
        <strong>{{ stats.total }}</strong>
      </div>
      <div class="metric">
        <span>目前來源</span>
        <strong>{{ stats.sources.length }}</strong>
      </div>
      <div class="metric">
        <span>目前分類</span>
        <strong>{{ stats.categories.length }}</strong>
      </div>
      <div class="metric metric-wide">
        <span>目前篩選</span>
        <strong>{{ activeSourceLabel }} / {{ activeCategoryLabel }}</strong>
      </div>
    </section>

    <section class="weekly-topics" aria-label="本週討論度前五名">
      <div class="panel-heading weekly-heading">
        <div>
          <p class="eyebrow">Weekly Signals</p>
          <h2>本週討論度 Top 5</h2>
        </div>
        <span>近 7 天</span>
      </div>

      <p v-if="!weeklyTopics.length" class="notice">尚無本週討論度資料。</p>
      <div v-else class="topic-chart">
        <article v-for="(topic, index) in weeklyTopics" :key="`${topic.topic_type}-${topic.name}`" class="topic-bar">
          <div class="topic-rank">{{ index + 1 }}</div>
          <div class="topic-main">
            <div class="topic-line">
              <div>
                <h3>{{ topic.name }}</h3>
                <p>
                  {{ topicTypeLabel(topic.topic_type) }} · {{ topic.article_count }} 篇文章 ·
                  {{ topic.source_count }} 個來源
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

    <section class="workspace">
      <aside class="filters-panel" aria-label="篩選條件">
        <label class="search-label" for="article-search">搜尋</label>
        <input
          id="article-search"
          v-model="filters.query"
          class="search-input"
          type="search"
          placeholder="搜尋標題、摘要或關鍵字"
        />

        <div class="filter-section">
          <p>熱門實體</p>
          <div v-if="topEntities.length" class="entity-list">
            <span v-for="entity in topEntities" :key="entity.id" class="entity-pill">
              {{ entity.canonical_name }}
              <small>{{ entityTypeLabel(entity.entity_type) }} · {{ entity.mention_count }}</small>
            </span>
          </div>
          <p v-else class="muted-note">尚未建立實體資料。</p>
        </div>

        <div class="filter-section">
          <p>來源</p>
          <button
            class="chip"
            :class="{ active: !filters.source }"
            type="button"
            @click="filters.source = ''"
          >
            全部
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
          <p>分類</p>
          <button
            class="chip"
            :class="{ active: !filters.category }"
            type="button"
            @click="filters.category = ''"
          >
            全部
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

      <section class="feed-panel" aria-label="文章列表">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Inbox</p>
            <h2>文章列表</h2>
          </div>
          <span>{{ articles.length }} 筆</span>
        </div>

        <p v-if="error" class="notice">{{ error }}</p>
        <p v-else-if="loading" class="notice">讀取文章中...</p>
        <p v-else-if="!articles.length" class="notice">沒有符合條件的文章。</p>

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
              <span class="score-badge">趨勢 {{ formatTrendScore(article.trend_score) }}</span>
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

      <section class="detail-panel" aria-label="文章摘要">
        <div v-if="detailLoading" class="empty-detail">讀取摘要中...</div>
        <div v-else-if="!selectedArticle" class="empty-detail">選擇一篇文章查看摘要</div>
        <article v-else class="article-detail">
          <div class="detail-meta">
            <span>{{ selectedArticle.source }}</span>
            <span>{{ selectedArticle.category }}</span>
            <span>{{ selectedArticle.published || selectedArticle.created_at }}</span>
          </div>
          <h2>{{ selectedArticle.title }}</h2>
          <a :href="selectedArticle.link" target="_blank" rel="noreferrer">開啟原文</a>

          <section class="trend-box" aria-label="趨勢分數">
            <div>
              <span>趨勢分數</span>
              <strong>{{ formatTrendScore(selectedArticle.trend_score) }}</strong>
            </div>
            <p>{{ selectedArticle.trend_reason || "尚無分數解釋。" }}</p>
            <div class="component-grid">
              <span
                v-for="component in trendComponentEntries(selectedArticle.trend_components)"
                :key="component.key"
              >
                {{ component.label }} <strong>{{ component.value }}</strong>
              </span>
            </div>
          </section>

          <section v-if="selectedArticle.entities?.length" class="detail-entities" aria-label="相關實體">
            <h3>相關工具 / 模型 / 公司</h3>
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
