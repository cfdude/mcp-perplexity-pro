import type { ModelRegistry, PerplexityModel, ModelCapability } from './types.js';

// Comprehensive model registry with capabilities and use cases
export const MODEL_REGISTRY: ModelRegistry = {
  sonar: {
    type: 'search',
    speed: 'fast',
    cost: 'low',
    bestFor: [
      'quick facts',
      'simple queries',
      'basic summaries',
      'current events',
      'straightforward questions',
    ],
    description:
      'Lightweight, cost-effective search model with grounding. Best for quick factual queries and simple information retrieval.',
    capabilities: {
      search: true,
      reasoning: false,
      realTime: true,
      research: false,
    },
  },
  'sonar-pro': {
    type: 'search',
    speed: 'medium',
    cost: 'medium',
    bestFor: [
      'complex queries',
      'follow-up questions',
      'detailed summaries',
      'product comparisons',
      'multi-part questions',
    ],
    description:
      'Advanced search offering with grounding, supporting complex queries and follow-ups. Ideal for detailed information synthesis.',
    capabilities: {
      search: true,
      reasoning: false,
      realTime: true,
      research: false,
    },
  },
  'sonar-reasoning-pro': {
    type: 'reasoning',
    speed: 'medium',
    cost: 'high',
    bestFor: [
      'complex analysis',
      'detailed reasoning',
      'multi-step problems',
      'chain of thought',
      'informed recommendations',
    ],
    description:
      'Precise reasoning offering powered by DeepSeek-R1 with Chain of Thought (CoT). Best for complex analytical tasks requiring detailed thinking.',
    capabilities: {
      search: true,
      reasoning: true,
      realTime: true,
      research: false,
    },
  },
  'sonar-deep-research': {
    type: 'research',
    speed: 'slow',
    cost: 'high',
    bestFor: [
      'comprehensive reports',
      'exhaustive research',
      'literature reviews',
      'market analysis',
      'in-depth investigations',
    ],
    description:
      'Expert-level research model conducting exhaustive searches and generating comprehensive reports. Ideal for thorough research projects.',
    capabilities: {
      search: true,
      reasoning: true,
      realTime: false,
      research: true,
    },
  },
};

/**
 * Intelligent model selection based on query characteristics
 * Analyzes the query content and selects the most appropriate model
 */
export function selectOptimalModel(
  query: string,
  explicitModel?: PerplexityModel,
  defaultModel: PerplexityModel = 'sonar-reasoning-pro'
): PerplexityModel {
  // If user explicitly specified a model, use it
  if (explicitModel && isValidModel(explicitModel)) {
    return explicitModel;
  }

  // Analyze query characteristics
  const queryLower = query.toLowerCase();
  const words = queryLower.split(/\s+/);

  // Deep research indicators - high priority
  const researchKeywords = [
    'comprehensive',
    'exhaustive',
    'detailed report',
    'research',
    'analyze all',
    'investigate',
    'literature review',
    'market analysis',
    'in-depth',
    'thorough',
    'complete analysis',
  ];

  if (researchKeywords.some(keyword => queryLower.includes(keyword))) {
    return 'sonar-deep-research';
  }

  // Complex reasoning indicators
  const complexReasoningKeywords = [
    'step by step',
    'step-by-step',
    'analyze',
    'explain how',
    'reasoning',
    'solve',
    'complex',
    'chain of thought',
    'think through',
    'break down',
    'detailed explanation',
  ];

  if (complexReasoningKeywords.some(keyword => queryLower.includes(keyword))) {
    return 'sonar-reasoning-pro';
  }

  // Quick reasoning needs (uses sonar-pro for cost efficiency, sonar-reasoning-pro for complex analysis)
  const quickReasoningKeywords = [
    'why',
    'how does',
    'explain',
    'compare',
    'analyze briefly',
    'quick analysis',
    'understand',
    'logic',
  ];

  if (quickReasoningKeywords.some(keyword => queryLower.includes(keyword))) {
    return 'sonar-pro';
  }

  // Enhanced search needs
  const enhancedSearchKeywords = [
    'detailed',
    'multiple',
    'various',
    'follow up',
    'follow-up',
    'comparison',
    'pros and cons',
    'alternatives',
    'options',
  ];

  if (enhancedSearchKeywords.some(keyword => queryLower.includes(keyword))) {
    return 'sonar-pro';
  }

  // Simple factual queries
  const simpleQueryIndicators = [
    'what is',
    'when',
    'where',
    'who',
    'simple',
    'quick',
    'brief',
    'fact',
    'date',
    'price',
    'cost',
  ];

  if (
    simpleQueryIndicators.some(indicator => queryLower.includes(indicator)) ||
    words.length <= 5
  ) {
    return 'sonar';
  }

  // Default to balanced model for general queries
  return defaultModel;
}

/**
 * Validates if a model name is supported
 */
export function isValidModel(model: string): model is PerplexityModel {
  return Object.keys(MODEL_REGISTRY).includes(model);
}

/**
 * Gets model information by name
 */
export function getModelInfo(model: PerplexityModel): ModelCapability {
  return MODEL_REGISTRY[model];
}

/**
 * Gets model capabilities in boolean format for compatibility
 */
export function getModelCapabilities(
  model: string
): { search: boolean; reasoning: boolean; realTime: boolean; research: boolean } | undefined {
  if (!isValidModel(model)) {
    return undefined;
  }

  const info = MODEL_REGISTRY[model];
  return info.capabilities;
}

/**
 * Suggests a fallback model based on the original model and context
 */
export function suggestFallbackModel(
  originalModel: PerplexityModel,
  errorType?: string
): PerplexityModel {
  const modelInfo = MODEL_REGISTRY[originalModel];

  // If rate limited, suggest a faster/cheaper alternative
  if (errorType === 'rate_limit') {
    switch (originalModel) {
      case 'sonar-deep-research':
        return 'sonar-reasoning-pro';
      case 'sonar-reasoning-pro':
        return 'sonar-pro';
      case 'sonar-pro':
        return 'sonar';
      default:
        return 'sonar';
    }
  }

  // For other errors, suggest a model of the same type but different tier
  switch (modelInfo.type) {
    case 'research':
      return 'sonar-reasoning-pro';
    case 'reasoning':
      return 'sonar-pro';
    case 'search':
      return originalModel === 'sonar-pro' ? 'sonar' : 'sonar-pro';
    default:
      return 'sonar-reasoning-pro';
  }
}

/**
 * Gets all models of a specific type
 */
export function getModelsByType(type: 'search' | 'reasoning' | 'research'): PerplexityModel[] {
  return Object.entries(MODEL_REGISTRY)
    .filter(([, info]) => info.type === type)
    .map(([model]) => model as PerplexityModel);
}

/**
 * Gets model recommendations based on use case
 */
export function getModelRecommendations(useCase: string): PerplexityModel[] {
  const useCaseLower = useCase.toLowerCase();
  const recommendations: PerplexityModel[] = [];

  Object.entries(MODEL_REGISTRY).forEach(([model, info]) => {
    if (info.bestFor.some(use => useCaseLower.includes(use.toLowerCase()))) {
      recommendations.push(model as PerplexityModel);
    }
  });

  return recommendations.length > 0 ? recommendations : ['sonar-reasoning-pro'];
}

/**
 * Formats model information for display
 */
export function formatModelInfo(model: PerplexityModel): string {
  const info = MODEL_REGISTRY[model];
  return `${model} (${info.type}, ${info.speed} speed, ${info.cost} cost): ${info.description}`;
}

/**
 * Gets a summary of all available models
 */
export function getModelSummary(): string {
  const summary = Object.entries(MODEL_REGISTRY)
    .map(([model, info]) => `- ${model}: ${info.description}`)
    .join('\n');

  return `Available Perplexity Models:\n${summary}`;
}
