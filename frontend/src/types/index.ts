// 全局 TypeScript 类型定义

export type PlatformType = 'bilibili' | 'youtube' | 'google' | 'github' | 'xiaohongshu' | 'zhihu' | 'wechat' | 'stackoverflow' | 'arxiv' | 'tavily' | 'other';

export interface Material {
  id: string;
  type: PlatformType;
  name: string;           // 截断至 20 字符显示
  url?: string;
  status: 'parsing' | 'chunking' | 'ready' | 'error';
  addedAt: string;        // ISO 8601
  viewedAt?: string;      // 首次查看时间，未查看则为 undefined
  extraData?: Record<string, any>;  // 搜索来源材料的丰富数据
}

export interface SearchResult {
  id: string;
  title: string;
  url: string;
  platform: PlatformType;
  type?: string;           // 资源类型：article/question/video/repo 等
  description: string;    // 截断至 100 字符显示
  qualityScore: number;   // 0-1，显示时 ×10
  contentSummary?: string;              // AI 内容整理（markdown 格式）
  engagementMetrics?: Record<string, any>;  // 互动指标
  imageUrls?: string[];                 // 图片 URL 列表
  topComments?: string[];               // 高赞评论文本列表
  contentText?: string;                  // 正文原文
  recommendationReason?: string;         // 推荐理由
  keyPoints?: string[];                  // 核心观点
  commentSummary?: string;               // 评论结论摘要
  // 四层架构新增字段
  sourceTier?: string;                   // 所属层级：broad_web / community / developer / academic
  author?: string;                       // 作者
  publishTime?: string;                  // 发表时间（ISO 8601）
  fetchedAt?: string;                    // 抓取时间
  extractionMode?: string;               // 提取方式
  sourceMetadata?: Record<string, any>;  // 平台特有元数据
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  sources?: CitationSource[];
  createdAt: string;
  /** 用户消息附加的材料 ID 列表 */
  attachedMaterialIds?: string[];
  /** 搜索结果快照（search_needed 分支，持久化到 assistant message） */
  searchResults?: InlineSearchResult[];
}

/** 聊天内联搜索结果条目 */
export interface InlineSearchResult {
  title: string;
  url: string;
  platform: PlatformType;
  description: string;
  score: number;
  /** AI 内容摘要 */
  contentSummary?: string;
  /** 正文原文（截断） */
  contentText?: string;
  /** 评论结论摘要 */
  commentSummary?: string;
  /** 热门评论预览 */
  commentsPreview?: string[];
  /** 图片 URL 列表 */
  imageUrls?: string[];
  /** 互动数据 */
  engagementMetrics?: Record<string, number>;
  /** 推荐理由 */
  recommendationReason?: string;
  /** 核心观点 */
  keyPoints?: string[];
  /** 来源层级：broad_web / community / developer / academic */
  sourceTier?: string;
  /** 作者 */
  author?: string;
  /** 发表时间 */
  publishTime?: string;
  /** 提取方式 */
  extractionMode?: string;
  /** 平台特有元数据（含 trace） */
  sourceMetadata?: Record<string, any>;
}

export interface CitationSource {
  materialId: string;
  materialName: string;
  snippet: string;
}

export interface DayProgress {
  dayNumber: number;
  title: string;
  completed: boolean;
  tasks: DayTask[];
}

export interface DayTask {
  id: string;
  type: 'video' | 'reading' | 'exercise' | 'flashcard';
  title: string;
  qualityScore?: number;
  completed: boolean;
}

export interface Note {
  id: string;
  title: string;
  content: string;        // Markdown 格式
  updatedAt: string;
}

export interface GeneratedContent {
  id: string;
  type: 'learning-plan' | 'study-guide' | 'flashcards' | 'quiz' | 'progress-report' | 'mind-map' | 'day-summary';
  title: string;
  content: string;        // Markdown 格式
  createdAt: string;
  version?: number;                    // 当前版本号（从 1 开始）
  versions?: GeneratedContentVersion[]; // 历史版本（最新在前）
}

export interface GeneratedContentVersion {
  content: string;
  createdAt: string;
  version: number;
}

export interface LearningPlan {
  id: string;
  title: string;
  sourceCount: number;
  lastAccessedAt: string;
  coverColor: string;     // Tailwind 颜色类
  totalDays: number;
  completedDays: number;
}

export type StudioToolType = 'learning-plan' | 'progress-report' | 'quiz' | 'study-guide' | 'flashcards' | 'notes' | 'mind-map' | 'day-summary';

export interface StudioTool {
  type: StudioToolType;
  icon: string;
  label: string;
}

export type LibraryTab = 'ai-generated' | 'my-notes';

export type PlatformSearchStatus = 'idle' | 'searching' | 'done' | 'timeout';

export interface SearchHistoryEntry {
  id: string;
  query: string;
  platforms: PlatformType[];
  results: SearchResult[];
  resultCount: number;
  searchedAt: string;     // ISO 8601
  status?: 'searching' | 'done' | 'error';
}

export type SearchStage = 'idle' | 'searching' | 'filtering' | 'extracting' | 'evaluating' | 'done' | 'error';

export interface LearnerProfile {
  goal: string;
  duration: number;        // 3-28 天数
  level: string;
  background: string;
  dailyHours: string;
}
