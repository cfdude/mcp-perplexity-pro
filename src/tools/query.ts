import type {
  AskPerplexityParams,
  ResearchPerplexityParams,
  Config,
  PerplexityResponse,
  PerplexityStreamChunk,
  StreamingCallbacks,
  ErrorResponse,
  MCPResponse,
} from '../types.js';
import { PerplexityApiClient } from '../perplexity-api.js';
import { StorageManager, StorageError } from '../storage.js';
import { selectOptimalModel } from '../models.js';

/**
 * Handles the ask_perplexity tool - stateless queries with optional streaming
 */
export async function handleAskPerplexity(
  params: AskPerplexityParams,
  config: Config,
  streamingCallbacks?: StreamingCallbacks
): Promise<MCPResponse> {
  console.log('handleAskPerplexity called with:', { query: params.query, model: params.model });
  console.log('Config API key:', config.api_key ? config.api_key.substring(0, 10) + '...' : 'MISSING');
  
  try {
    const apiClient = new PerplexityApiClient(config);

    // Detect project and create project-aware config if saving is requested
    let storageManager: StorageManager | undefined;
    let projectName: string | undefined;
    let projectConfig: Config | undefined;
    
    if (params.save_report) {
      const { detectProjectWithSuggestions } = await import('./projects.js');
      projectName = await detectProjectWithSuggestions(params.project_name, config);
      
      // Create project-specific storage config with ask subdirectory
      projectConfig = {
        ...config,
        storage_path: `projects/${projectName}/ask`
      };
      
      storageManager = new StorageManager(projectConfig);
    }

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

    // Use streaming if callbacks are provided, otherwise use regular completion
    let response: PerplexityResponse;
    let content: string;

    if (streamingCallbacks) {
      // Stream the response with real-time callbacks
      response = await apiClient.chatCompletionStream(request, streamingCallbacks);
      content = response.choices[0]?.message?.content || 'No response generated';
    } else {
      // Use regular completion
      response = await apiClient.chatCompletion(request);
      content = response.choices[0]?.message?.content || 'No response generated';
    }
    
    // Save report if requested
    let reportSaved = false;
    let reportPath: string | undefined;
    
    if (params.save_report && storageManager && projectName && content) {
      try {
        const reportId = await storageManager.saveReport(content, params.query);
        reportSaved = true;
        reportPath = `projects/${projectName}/ask/reports/${reportId}`;
      } catch (storageError) {
        // Don't fail the entire request if saving fails
        console.warn('Failed to save ask report:', storageError);
      }
    }
    
    // Construct response text with save information if applicable
    let responseText = content;
    if (params.save_report) {
      if (reportSaved && reportPath) {
        responseText += `\n\n---\n**Report saved to:** ${reportPath}`;
      } else {
        responseText += '\n\n---\n**Note:** Report save was requested but failed.';
      }
    }
    
    return {
      content: [
        {
          type: 'text',
          text: responseText,
        },
      ],
    };
  } catch (error) {
    const errorResponse = PerplexityApiClient.handleError(error, {
      model: params.model || config.default_model,
      query: params.query,
    });

    return {
      content: [
        {
          type: 'text',
          text: `Error: ${errorResponse.error.message}`,
        },
      ],
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
  (PerplexityResponse & { report_saved?: boolean; report_path?: string }) | ErrorResponse
> {
  try {
    const apiClient = new PerplexityApiClient(config);
    
    // Detect project and create project-aware config
    const { detectProjectWithSuggestions } = await import('./projects.js');
    const projectName = await detectProjectWithSuggestions(params.project_name, config);
    
    // Create project-specific storage config with research subdirectory
    const projectConfig = {
      ...config,
      storage_path: `projects/${projectName}/research`
    };
    
    const storageManager = new StorageManager(projectConfig);

    // Use sonar-deep-research by default, but allow override
    const selectedModel = params.model || 'sonar-deep-research';
    
    // For sonar-deep-research, automatically use async processing to avoid timeouts
    if (selectedModel === 'sonar-deep-research') {
      console.warn('Using sonar-deep-research model - consider using async_perplexity for long queries to avoid timeouts');
      // Continue with synchronous processing but with warning
    }

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
        reportPath = `projects/${projectName}/research/reports/${reportId}`;
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
