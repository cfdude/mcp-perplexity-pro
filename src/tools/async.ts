import type {
  AsyncPerplexityParams,
  CheckAsyncParams,
  Config,
  AsyncJob,
  ErrorResponse,
} from '../types.js';
import { PerplexityApiClient } from '../perplexity-api.js';
import { selectOptimalModel } from '../models.js';

/**
 * Handles the async_perplexity tool - creates async jobs for long-running queries
 */
export async function handleAsyncPerplexity(
  params: AsyncPerplexityParams,
  config: Config
): Promise<
  | (AsyncJob & {
      selected_model: string;
      model_selection_reason: string;
      estimated_completion: string;
    })
  | ErrorResponse
> {
  try {
    const apiClient = new PerplexityApiClient(config);

    // Detect project and create project-aware config
    const { detectProjectWithSuggestions } = await import('./projects.js');
    const projectName = await detectProjectWithSuggestions(undefined, config);
    
    // Create project-specific storage config with async subdirectory
    const projectConfig = {
      ...config,
      storage_path: `projects/${projectName}/async`
    };

    // Select optimal model based on query or use explicit model
    const selectedModel = selectOptimalModel(params.query, params.model, config.default_model);

    // Prepare the async request
    const request = {
      model: selectedModel,
      messages: [{ role: 'user' as const, content: params.query }],
      temperature: params.temperature ?? 0.2,
      ...(params.max_tokens && { max_tokens: params.max_tokens }),
    };

    const response = await apiClient.createAsyncChatCompletion(request);

    // Estimate completion time based on model type and complexity
    const estimatedMinutes = getEstimatedCompletionTime(selectedModel, params.query);
    const estimatedCompletion = new Date(Date.now() + estimatedMinutes * 60 * 1000).toISOString();

    return {
      ...response,
      selected_model: selectedModel,
      model_selection_reason: params.model ? 'user_specified' : 'auto_selected',
      estimated_completion: estimatedCompletion,
    } as AsyncJob & {
      selected_model: string;
      model_selection_reason: string;
      estimated_completion: string;
    };
  } catch (error) {
    return PerplexityApiClient.handleError(error, {
      model: params.model || config.default_model,
      query: params.query,
    });
  }
}

/**
 * Handles the check_async_perplexity tool - checks status of async jobs
 */
export async function handleCheckAsync(
  params: CheckAsyncParams,
  config: Config
): Promise<
  | (AsyncJob & {
      completion_percentage?: number;
      next_check_recommended?: string;
    })
  | ErrorResponse
> {
  try {
    const apiClient = new PerplexityApiClient(config);
    
    // Note: async job checking doesn't need project-aware config since
    // job IDs are global and not project-specific
    const response = await apiClient.getAsyncJob(params.job_id);

    // Add helpful metadata for job monitoring
    let completionPercentage: number | undefined;
    let nextCheckRecommended: string | undefined;

    switch (response.status) {
      case 'CREATED':
        completionPercentage = 10;
        nextCheckRecommended = new Date(Date.now() + 30 * 1000).toISOString(); // 30 seconds
        break;
      case 'STARTED':
        completionPercentage = 50;
        nextCheckRecommended = new Date(Date.now() + 60 * 1000).toISOString(); // 1 minute
        break;
      case 'COMPLETED':
        completionPercentage = 100;
        break;
      case 'FAILED':
        completionPercentage = 0;
        break;
    }

    return {
      ...response,
      ...(completionPercentage !== undefined && { completion_percentage: completionPercentage }),
      ...(nextCheckRecommended && { next_check_recommended: nextCheckRecommended }),
    } as AsyncJob & {
      completion_percentage?: number;
      next_check_recommended?: string;
    };
  } catch (error) {
    return PerplexityApiClient.handleError(error, {
      query: `Async job check: ${params.job_id}`,
    });
  }
}

/**
 * Handles the list_async_jobs tool - lists all async jobs
 */
export async function handleListAsyncJobs(
  config: Config,
  limit = 20,
  nextToken?: string
): Promise<
  | {
      jobs: (AsyncJob & { time_since_created: string; estimated_time_remaining?: string })[];
      next_token?: string;
      total_jobs: number;
    }
  | ErrorResponse
> {
  try {
    const apiClient = new PerplexityApiClient(config);
    
    // Note: listing async jobs doesn't need project-aware config since
    // jobs are listed globally, not per project
    const response = await apiClient.listAsyncJobs(limit, nextToken);

    // Add helpful metadata to each job
    const enrichedJobs = response.jobs.map(job => {
      const timeSinceCreated = formatTimeDuration(Date.now() - job.created_at * 1000);
      let estimatedTimeRemaining: string | undefined;

      // Estimate remaining time for active jobs
      if (job.status === 'CREATED' || job.status === 'STARTED') {
        const elapsedMinutes = (Date.now() - job.created_at * 1000) / (1000 * 60);
        const estimatedTotalMinutes = getEstimatedCompletionTime(job.model, 'complex query');
        const remainingMinutes = Math.max(0, estimatedTotalMinutes - elapsedMinutes);
        estimatedTimeRemaining = `${Math.ceil(remainingMinutes)} minutes`;
      }

      return {
        ...job,
        time_since_created: timeSinceCreated,
        ...(estimatedTimeRemaining && { estimated_time_remaining: estimatedTimeRemaining }),
      };
    });

    return {
      jobs: enrichedJobs,
      ...(response.next_token && { next_token: response.next_token }),
      total_jobs: response.jobs.length,
    };
  } catch (error) {
    return PerplexityApiClient.handleError(error, {
      query: 'List async jobs',
    });
  }
}

/**
 * Estimates completion time based on model and query complexity
 */
function getEstimatedCompletionTime(model: string, query: string): number {
  // Base times in minutes
  const baseTimes = {
    sonar: 0.5,
    'sonar-pro': 1,
    'sonar-reasoning': 1.5,
    'sonar-reasoning-pro': 3,
    'sonar-deep-research': 5,
  };

  let baseTime = baseTimes[model as keyof typeof baseTimes] || 2;

  // Adjust based on query complexity
  const queryLength = query.length;
  const complexityKeywords = [
    'comprehensive',
    'detailed',
    'analysis',
    'research',
    'compare',
    'evaluate',
    'investigate',
  ];

  // Add time for query length
  if (queryLength > 500) baseTime *= 1.5;
  else if (queryLength > 200) baseTime *= 1.2;

  // Add time for complexity keywords
  const complexityScore = complexityKeywords.reduce(
    (score, keyword) => score + (query.toLowerCase().includes(keyword) ? 1 : 0),
    0
  );
  baseTime *= 1 + complexityScore * 0.3;

  return Math.ceil(baseTime);
}

/**
 * Formats time duration in a human-readable format
 */
function formatTimeDuration(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) return `${days}d ${hours % 24}h`;
  if (hours > 0) return `${hours}h ${minutes % 60}m`;
  if (minutes > 0) return `${minutes}m ${seconds % 60}s`;
  return `${seconds}s`;
}
