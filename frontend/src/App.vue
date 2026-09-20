<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import {
  getArticle,
  getArticleDates,
  getArticles,
  getGithubTop,
  getHuggingFaceTop,
  getProjectAdvice,
  getStats,
  getTopicRankings,
} from "./api";

const stats = ref({
  total: 0,
  sources: [],
  categories: [],
  latest_created: "",
});
const articleDates = ref([]);
const articles = ref([]);
const recentFocusTopics = ref([]);
const todayTopics = ref([]);
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

const activeSourceLabel = computed(() => filters.source || "全部來源");
const activeCategoryLabel = computed(() => filters.category || "全部分類");
const selectedDate = ref("");
const selectedDateIndex = computed(() => {
  return articleDates.value.findIndex((item) => item.date === selectedDate.value);
});
const olderDate = computed(() => {
  const index = selectedDateIndex.value;
  return index >= 0 ? articleDates.value[index + 1] : null;
});
const newerDate = computed(() => {
  const index = selectedDateIndex.value;
  return index > 0 ? articleDates.value[index - 1] : null;
});
const selectedDateCount = computed(() => {
  const selected = articleDates.value.find((item) => item.date === selectedDate.value);
  return selected?.count || articles.value.length;
});

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

function importanceStars(value) {
  const score = Number(value || 0);
  const level = Math.max(0, Math.min(5, Math.ceil(score / 20)));
  return "★".repeat(level) + "☆".repeat(5 - level);
}

function formatPlatformMetric(value) {
  const number = Number(value || 0);
  return new Intl.NumberFormat("en-US", { notation: "compact" }).format(number);
}

function sourceTypeLabel(type) {
  const labels = {
    github: "GitHub",
    huggingface_model: "Hugging Face 模型",
    huggingface_dataset: "Hugging Face 資料集",
    paper: "研究論文",
    web: "Web",
  };
  return labels[type] || type || "來源";
}

async function loadStats() {
  stats.value = await getStats();
}

async function loadArticleDates() {
  articleDates.value = await getArticleDates();
  if (!articleDates.value.length) {
    selectedDate.value = "";
    return;
  }

  const stillAvailable = articleDates.value.some((item) => item.date === selectedDate.value);
  if (!selectedDate.value || !stillAvailable) {
    selectedDate.value = articleDates.value[0].date;
  }
}

async function loadTopicRankings() {
  const [recentFocus, today] = await Promise.all([
    getTopicRankings("all", 5),
    getTopicRankings("today", 5),
  ]);
  recentFocusTopics.value = recentFocus;
  todayTopics.value = today;
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
    articles.value = await getArticles({ ...filters, date: selectedDate.value });
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
    error.value = "讀取文章失敗，請確認 API 是否正常運作。";
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
    projectError.value = "搜尋分析失敗，請確認 API key 與後端紀錄。";
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

function selectDate(date) {
  if (date) {
    selectedDate.value = date;
  }
}

function showOlderDate() {
  if (olderDate.value) {
    selectDate(olderDate.value.date);
  }
}

function showNewerDate() {
  if (newerDate.value) {
    selectDate(newerDate.value.date);
  }
}

watch(
  () => [filters.source, filters.category, selectedDate.value],
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
  await loadTopicRankings();
  await loadPlatformRankings();
  await loadArticleDates();
  await loadArticles();
});
</script>

<template>
  <main class="app-shell">
    <header class="hero">
      <div class="hero-copy">
        <p class="eyebrow">AI Trend Desk</p>
        <h1>AI趨勢整平台</h1>
      </div>
      <div class="hero-status">
        <span>已收錄 {{ stats.total }} 篇</span>
        <span>最近更新：{{ stats.latest_created || "尚無資料" }}</span>
      </div>
    </header>

    <section class="metrics" aria-label="資料總覽">
      <div class="metric">
        <span>文章總數</span>
        <strong>{{ stats.total }}</strong>
      </div>
      <div class="metric">
        <span>來源數</span>
        <strong>{{ stats.sources.length }}</strong>
      </div>
      <div class="metric">
        <span>分類數</span>
        <strong>{{ stats.categories.length }}</strong>
      </div>
        <div class="metric metric-wide">
          <span>目前篩選</span>
          <strong>{{ selectedDate || "最新日期" }} / {{ activeSourceLabel }} / {{ activeCategoryLabel }}</strong>
        </div>
    </section>

    <section class="project-advisor" aria-label="技術資源探索">
      <div class="panel-heading advisor-heading">
        <div>
          <p class="eyebrow">Research Agent</p>
          <h2>技術資源探索</h2>
        </div>
        <span>自主搜尋與來源驗證</span>
      </div>
      <form class="advisor-form" @submit.prevent="analyzeProject">
        <input
          v-model="projectQuery"
          type="search"
          placeholder="描述你的想法、問題，或想找的專案、模型、資料集與論文"
        />
        <button type="submit" :disabled="projectLoading || !projectQuery.trim()">
          {{ projectLoading ? "搜尋中..." : "開始搜尋" }}
        </button>
      </form>

      <p v-if="projectError" class="notice">{{ projectError }}</p>
      <div v-if="projectAdvice" class="advisor-result">
        <section class="advisor-overview">
          <h3>搜尋結果</h3>
          <p class="advisor-answer">{{ projectAdvice.answer }}</p>
        </section>

        <section v-for="section in projectAdvice.sections" :key="section.title">
          <h3>{{ section.title }}</h3>
          <p v-if="section.summary" class="advisor-section-summary">{{ section.summary }}</p>
          <div v-if="section.items?.length" class="advisor-cards">
            <article v-for="item in section.items" :key="item.url">
              <div class="advisor-card-heading">
                <a :href="item.url" target="_blank" rel="noreferrer">{{ item.title }}</a>
                <span>{{ sourceTypeLabel(item.source_type) }}</span>
              </div>
              <p>{{ item.description }}</p>
              <dl class="advisor-facts">
                <div>
                  <dt>運作方式</dt>
                  <dd>{{ item.how_it_works }}</dd>
                </div>
                <div>
                  <dt>適合原因</dt>
                  <dd>{{ item.why_relevant }}</dd>
                </div>
                <div>
                  <dt>限制</dt>
                  <dd>{{ item.limitations || "未發現明確限制。" }}</dd>
                </div>
                <div>
                  <dt>查閱依據</dt>
                  <dd>{{ item.evidence_basis }}</dd>
                </div>
              </dl>
            </article>
          </div>
        </section>
      </div>
    </section>

    <section class="weekly-topics" aria-label="近期焦點排行">
      <div class="panel-heading weekly-heading">
        <div>
          <p class="eyebrow">Focus Signals</p>
          <h2>近期焦點 TOP 5</h2>
        </div>
        <span>每日累積</span>
      </div>

      <p v-if="!recentFocusTopics.length" class="notice">尚無近期焦點資料。</p>
      <div v-else class="topic-chart">
        <article v-for="(topic, index) in recentFocusTopics" :key="topic.term" class="topic-bar">
          <div class="topic-rank">{{ index + 1 }}</div>
          <div class="topic-main">
            <div class="topic-line">
              <div>
                <h3>{{ topic.term }}</h3>
                <p>
                  {{ topic.source_count }} 個來源 / {{ topic.article_count }} 篇文章
                </p>
              </div>
              <strong>{{ Number(topic.topic_score || 0).toFixed(1) }}</strong>
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

    <section class="emerging-topics" aria-label="本日話題排行">
      <div class="panel-heading weekly-heading">
        <div>
          <p class="eyebrow">Today Signals</p>
          <h2>本日話題 TOP 5</h2>
        </div>
        <span>今日新增</span>
      </div>

      <p v-if="!todayTopics.length" class="notice">尚無本日話題資料。</p>
      <div v-else class="emerging-list">
        <article v-for="(topic, index) in todayTopics" :key="topic.term" class="emerging-item">
          <div class="topic-rank">{{ index + 1 }}</div>
          <div class="emerging-main">
            <h3>{{ topic.term }}</h3>
            <div class="emerging-metrics">
              <span>{{ topic.source_count }} 個來源</span>
              <span>{{ topic.article_count }} 篇文章</span>
            </div>
          </div>
          <strong>{{ Number(topic.topic_score || 0).toFixed(1) }}</strong>
        </article>
      </div>
    </section>

    <section class="platform-rankings" aria-label="平台熱門排行榜">
      <div class="platform-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">GitHub</p>
            <h2>GitHub Stars Top 10</h2>
          </div>
          <span>stars</span>
        </div>
        <p v-if="!githubTop.length" class="notice">尚無 GitHub 排行資料。</p>
        <ol v-else class="ranking-list">
          <li v-for="item in githubTop" :key="item.item_id">
            <span class="ranking-index">{{ item.rank }}</span>
            <div class="ranking-main">
              <a :href="item.url" target="_blank" rel="noreferrer">{{ item.name }}</a>
              <p>{{ item.description || "No description" }}</p>
              <details
                v-if="
                  item.ai_analysis?.what_it_does ||
                  item.ai_analysis?.best_for
                "
                class="ranking-analysis"
              >
                <summary>AI 解讀</summary>
                <div class="ranking-analysis-body">
                  <div v-if="item.ai_analysis?.what_it_does" class="analysis-row">
                    <span>在做什麼</span>
                    <p>{{ item.ai_analysis.what_it_does }}</p>
                  </div>
                  <div v-if="item.ai_analysis?.best_for" class="analysis-row">
                    <span>適合誰</span>
                    <p>{{ item.ai_analysis.best_for }}</p>
                  </div>
                </div>
              </details>
            </div>
            <strong class="ranking-metric">★ {{ formatPlatformMetric(item.primary_metric_value) }}</strong>
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
        <p v-if="!huggingFaceTop.length" class="notice">尚無 Hugging Face 排行資料。</p>
        <ol v-else class="ranking-list">
          <li v-for="item in huggingFaceTop" :key="item.item_id">
            <span class="ranking-index">{{ item.rank }}</span>
            <div class="ranking-main">
              <a :href="item.url" target="_blank" rel="noreferrer">{{ item.name }}</a>
              <p>{{ item.category || "model" }}</p>
              <details
                v-if="
                  item.ai_analysis?.what_it_does ||
                  item.ai_analysis?.best_for
                "
                class="ranking-analysis"
              >
                <summary>AI 解讀</summary>
                <div class="ranking-analysis-body">
                  <div v-if="item.ai_analysis?.what_it_does" class="analysis-row">
                    <span>在做什麼</span>
                    <p>{{ item.ai_analysis.what_it_does }}</p>
                  </div>
                  <div v-if="item.ai_analysis?.best_for" class="analysis-row">
                    <span>適合誰</span>
                    <p>{{ item.ai_analysis.best_for }}</p>
                  </div>
                </div>
              </details>
            </div>
            <strong class="ranking-metric">★ {{ formatPlatformMetric(item.primary_metric_value) }}</strong>
          </li>
        </ol>
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
          placeholder="搜尋文章或來源"
        />

        <div v-if="articleDates.length" class="filter-section">
          <p>日期</p>
          <select v-model="selectedDate" class="filter-select" aria-label="選擇文章日期">
            <option v-for="item in articleDates" :key="item.date" :value="item.date">
              {{ item.date }} / {{ item.count }} 篇
            </option>
          </select>
          <div class="date-navigation">
            <button
              type="button"
              :disabled="!olderDate"
              aria-label="前一天"
              title="前一天"
              @click="showOlderDate"
            >
              &lsaquo;
            </button>
            <span>當日收錄 {{ selectedDateCount }} 篇</span>
            <button
              type="button"
              :disabled="!newerDate"
              aria-label="後一天"
              title="後一天"
              @click="showNewerDate"
            >
              &rsaquo;
            </button>
          </div>
        </div>

        <div class="filter-section">
          <p>來源</p>
          <select v-model="filters.source" class="filter-select" aria-label="選擇文章來源">
            <option value="">全部來源</option>
            <option v-for="source in stats.sources" :key="source.source" :value="source.source">
              {{ source.source }} / {{ source.count }} 篇
            </option>
          </select>
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

      <section class="feed-panel" aria-label="article list">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Inbox</p>
            <h2>文章列表</h2>
          </div>
          <span>{{ selectedDate || "最新日期" }} · {{ articles.length }} 篇</span>
        </div>

        <p v-if="error" class="notice">{{ error }}</p>
        <p v-else-if="loading" class="notice">讀取文章中...</p>
        <p v-else-if="!articles.length" class="notice">沒有符合目前篩選條件的文章。</p>

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
              <span class="source">資料來源：{{ article.source }}</span>
              <span class="score-badge">重要度 {{ importanceStars(article.trend_score) }}</span>
            </div>
            <h3>{{ article.title }}</h3>
            <p>{{ plainPreview(article.preview) }}</p>
            <div class="card-footer">
              <span>{{ article.category }}</span>
              <span>{{ article.published || article.created_at }}</span>
            </div>
          </button>
        </div>
      </section>

      <section class="detail-panel" aria-label="文章詳細內容">
        <div v-if="detailLoading" class="empty-detail">讀取詳細內容中...</div>
        <div v-else-if="!selectedArticle" class="empty-detail">選擇一篇文章查看詳細內容</div>
        <article v-else class="article-detail">
          <div class="detail-meta">
            <span>{{ selectedArticle.source }}</span>
            <span>{{ selectedArticle.category }}</span>
            <span>{{ selectedArticle.published || selectedArticle.created_at }}</span>
          </div>
          <h2>{{ selectedArticle.title }}</h2>
          <a :href="selectedArticle.link" target="_blank" rel="noreferrer">閱讀原文</a>

          <section class="trend-box" aria-label="重要度">
            <div>
              <span>重要度</span>
              <strong class="star-rating">{{ importanceStars(selectedArticle.trend_score) }}</strong>
            </div>
            <p>依文章重要性與來源權重評估。</p>
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
