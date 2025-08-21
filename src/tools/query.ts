import type {
  AskPerplexityParams,
  ResearchPerplexityParams,
  Config,
  PerplexityResponse,
  ErrorResponse,
  MCPResponse,
} from '../types.js';
import { PerplexityApiClient } from '../perplexity-api.js';
import { StorageManager, StorageError } from '../storage.js';
import { selectOptimalModel } from '../models.js';

/**
 * Handles the ask_perplexity tool - stateless queries
 */
export async function handleAskPerplexity(
  params: AskPerplexityParams,
  config: Config
): Promise<MCPResponse> {
  try {
    const apiClient = new PerplexityApiClient(config);
    
    // Select optimal model based on query or use explicit model
    const selectedModel = selectOptimalModel(params.query, params.model, config.default_model);

    // Prepare the request
    const request = {
      model: selectedModel,
      messages: [{ role: 'user' as const, content: params.query }],
      temperature: params.temperature ?? 0.2,
      ...(params.max_tokens && { max_tokens: params.max_tokens }),
      ...(params.search_domain_filter && { search_domain_filter: params.search_domain_filter }),
      ...(params.return_images !== undefined && { return_images: params.return_images }),
      ...(params.return_related_questions !== undefined && {
        return_related_questions: params.return_related_questions,
      }),
    };

    const response = await apiClient.chatCompletion(request);

    // Convert to MCP response format
    const content = response.choices[0]?.message?.content || 'No response generated';
    return {
      content: [{
        type: 'text',
        text: content
      }]
    };
  } catch (error) {
    const errorResponse = PerplexityApiClient.handleError(error, {
      model: params.model || config.default_model,
      query: params.query,
    });
    
    return {
      content: [{
        type: 'text',
        text: `Error: ${errorResponse.error.message}`
      }]
    };
  }
}

/**
 * Handles the research_perplexity tool - deep research with optional saving
 */
export async function handleResearchPerplexity(
  params: ResearchPerplexityParams,
  config: Config
): Promise<
  | (PerplexityResponse & { report_saved?: boolean; report_path?: string })
  | ErrorResponse
> {
  try {
    const apiClient = new PerplexityApiClient(config);
    const storageManager = new StorageManager(config);

    // Use sonar-deep-research by default, but allow override
    const selectedModel = params.model || 'sonar-deep-research';

    // Prepare the research request with comprehensive settings
    const request = {
      model: selectedModel,
      messages: [
        {
          role: 'system' as const,
          content:
            'You are a research expert. Provide comprehensive, well-structured research with clear citations and analysis. Include multiple perspectives and sources when available.',
        },
        { role: 'user' as const, content: params.topic },
      ],
      temperature: 0.1, // Lower temperature for more consistent research
      max_tokens: params.max_tokens || 4000, // Longer responses for research
      return_related_questions: true,
      web_search_options: {
        search_context_size: 'high' as const,
      },
    };

    const response = await apiClient.chatCompletion(request);

    // Save report if requested
    let reportSaved = false;
    let reportPath: string | undefined;

    if (params.save_report && response.choices[0]?.message?.content) {
      try {
        const reportId = await storageManager.saveReport(
          response.choices[0].message.content,
          params.topic
        );
        reportSaved = true;
        reportPath = `${config.storage_path}/${reportId}`;
      } catch (storageError) {
        // Don't fail the entire request if saving fails
        console.warn('Failed to save research report:', storageError);
      }
    }

    return {
      ...response,
      selected_model: selectedModel,
      model_selection_reason: params.model ? 'user_specified' : 'auto_selected_research',
      report_saved: reportSaved,
      ...(reportPath && { report_path: reportPath }),
    } as PerplexityResponse & {
      selected_model: string;
      model_selection_reason: string;
      report_saved: boolean;
      report_path?: string;
    };
  } catch (error) {
    if (error instanceof StorageError) {
      return StorageManager.handleError(error);
    }
    return PerplexityApiClient.handleError(error, {
      model: params.model || 'sonar-deep-research',
      query: params.topic,
    });
  }
}