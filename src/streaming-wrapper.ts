import type { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { PerplexityApiClient } from './perplexity-api.js';
import { selectOptimalModel } from './models.js';
import type { Config, AsyncJob, ErrorResponse } from './types.js';

/**
 * Progress tracking state for streaming operations
 */
interface StreamingState {
  jobId: string;
  progressToken: string | number;
  server: Server;
  startTime: number;
  lastProgress: number;
  toolName: string;
  params: any;
  config: Config;
}

/**
 * Active streaming operations registry
 */
const activeStreams = new Map<string, StreamingState>();

/**
 * Universal async tool wrapper that creates async jobs and streams progress to Claude Code
 */
export class StreamingWrapper {
  private server: Server;
  private config: Config;

  constructor(server: Server, config: Config) {
    this.server = server;
    this.config = config;
  }

  /**
   * Execute a tool call with streaming content updates (not just progress)
   */
  async executeWithStreaming(
    toolName: string,
    params: any,
    progressToken?: string | number
  ): Promise<any> {
    // If no progress token provided, execute synchronously (backwards compatibility)
    if (!progressToken) {
      return this.executeSynchronously(toolName, params);
    }

    try {
      // Create async job based on tool type
      const asyncJob = await this.createAsyncJob(toolName, params);
      
      if ('error' in asyncJob) {
        return asyncJob;
      }

      // Register streaming state
      const streamState: StreamingState = {
        jobId: asyncJob.id,
        progressToken,
        server: this.server,
        startTime: Date.now(),
        lastProgress: 0,
        toolName,
        params,
        config: this.config
      };
      
      activeStreams.set(asyncJob.id, streamState);

      // Start streaming content (not just progress)
      this.startContentStreaming(asyncJob.id);

      // Return initial response indicating streaming has started
      return {
        content: [{
          type: 'text',
          text: `🚀 Starting ${toolName}...\n\n`
        }]
      };

    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `Error: ${error instanceof Error ? error.message : String(error)}`
        }],
        isError: true
      };
    }
  }

  /**
   * Create async job based on tool type
   */
  private async createAsyncJob(toolName: string, params: any): Promise<AsyncJob | ErrorResponse> {
    const apiClient = new PerplexityApiClient(this.config);

    // Determine the query/content based on tool type
    let query: string;
    let model: string;
    
    switch (toolName) {
      case 'ask_perplexity':
        query = params.query;
        model = params.model || selectOptimalModel(query, undefined, this.config.default_model);
        break;
      
      case 'chat_perplexity':
        query = params.message;
        model = params.model || selectOptimalModel(query, undefined, this.config.default_model);
        break;
      
      case 'research_perplexity':
        query = params.topic;
        model = params.model || 'sonar-deep-research';
        break;
      
      default:
        throw new Error(`Unsupported tool for streaming: ${toolName}`);
    }

    // Create the async request
    const request = {
      model,
      messages: [{ role: 'user' as const, content: query }],
      temperature: params.temperature ?? 0.2,
      ...(params.max_tokens && { max_tokens: params.max_tokens }),
      ...(params.search_domain_filter && { search_domain_filter: params.search_domain_filter }),
      ...(params.return_images && { return_images: params.return_images }),
      ...(params.return_related_questions && { return_related_questions: params.return_related_questions })
    };

    return await apiClient.createAsyncChatCompletion(request);
  }

  /**
   * Execute tool synchronously (fallback for no progress token)
   */
  private async executeSynchronously(toolName: string, params: any): Promise<any> {
    // Import handlers dynamically to avoid circular dependencies
    const { handleAskPerplexity, handleResearchPerplexity } = await import('./tools/query.js');
    const { handleChatPerplexity } = await import('./tools/chat.js');

    switch (toolName) {
      case 'ask_perplexity':
        return await handleAskPerplexity(params, this.config);
      
      case 'chat_perplexity':
        const result = await handleChatPerplexity(params, this.config);
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
      
      case 'research_perplexity':
        const researchResult = await handleResearchPerplexity(params, this.config);
        return { content: [{ type: 'text', text: JSON.stringify(researchResult, null, 2) }] };
      
      default:
        throw new Error(`Unknown tool: ${toolName}`);
    }
  }

  /**
   * Start streaming actual content from async job (not just progress)
   */
  private async startContentStreaming(jobId: string): Promise<void> {
    const state = activeStreams.get(jobId);
    if (!state) return;

    const apiClient = new PerplexityApiClient(this.config);
    let pollCount = 0;
    let lastContentLength = 0;
    const maxPolls = 60; // 5 minutes max (5s intervals)

    const pollAndStreamContent = async () => {
      try {
        const jobStatus = await apiClient.getAsyncJob(jobId);
        
        if (!activeStreams.has(jobId)) {
          // Stream was cancelled
          return;
        }

        pollCount++;
        const elapsedTime = Date.now() - state.startTime;
        
        // Check if we have new content to stream
        const currentContent = jobStatus.choices?.[0]?.message?.content || '';
        
        if (currentContent.length > lastContentLength) {
          // We have new content! Stream the delta
          const newContent = currentContent.slice(lastContentLength);
          await this.streamContentChunk(state, newContent, jobStatus.status);
          lastContentLength = currentContent.length;
        }

        // Send status updates for major state changes
        if (jobStatus.status === 'STARTED' && state.lastProgress < 25) {
          await this.streamContentChunk(state, '📡 Processing your request...\n\n', jobStatus.status);
          state.lastProgress = 25;
        }

        // Handle completion
        if (jobStatus.status === 'COMPLETED') {
          // Stream any remaining content
          if (currentContent.length > lastContentLength) {
            const finalContent = currentContent.slice(lastContentLength);
            await this.streamContentChunk(state, finalContent, jobStatus.status);
          }
          
          // Process final job result (save report, etc.)
          await this.handleJobCompletion(jobId, jobStatus);
          
          // Stream completion message
          await this.streamContentChunk(state, '\n\n✅ Complete!', 'COMPLETED');
          
          activeStreams.delete(jobId);
          return;
        } else if (jobStatus.status === 'FAILED') {
          await this.streamContentChunk(state, `\n\n❌ Job failed: ${jobStatus.error || 'Unknown error'}`, 'FAILED');
          activeStreams.delete(jobId);
          return;
        }

        // Continue polling if job is still running
        if (pollCount < maxPolls && (jobStatus.status === 'CREATED' || jobStatus.status === 'STARTED')) {
          setTimeout(pollAndStreamContent, 2000); // Poll every 2 seconds for more responsive streaming
        } else if (pollCount >= maxPolls) {
          // Timeout reached
          await this.streamContentChunk(state, '\n\n⏰ Request timed out after 5 minutes', 'FAILED');
          activeStreams.delete(jobId);
        }

      } catch (error) {
        console.error(`Error polling job ${jobId}:`, error);
        await this.streamContentChunk(state, `\n\n❌ Error: ${error instanceof Error ? error.message : String(error)}`, 'FAILED');
        activeStreams.delete(jobId);
      }
    };

    // Start polling immediately
    setTimeout(pollAndStreamContent, 500); // Start after 500ms
  }

  /**
   * Stream a chunk of content to Claude Code
   */
  private async streamContentChunk(
    state: StreamingState, 
    content: string, 
    status: string
  ): Promise<void> {
    try {
      // Use MCP's streaming capabilities to send partial content
      // This creates the illusion of real-time streaming by sending content in chunks
      await state.server.notification({
        method: 'notifications/message',
        params: {
          level: 'info',
          logger: `mcp-perplexity-${state.toolName}`,
          data: {
            type: 'content_chunk',
            content: content,
            job_id: state.jobId,
            status: status,
            timestamp: Date.now()
          }
        }
      } as any);

      // Also send to stdout for CLI clients that capture output
      process.stdout.write(content);
      
    } catch (error) {
      console.error('Error streaming content chunk:', error);
    }
  }

  /**
   * Legacy method - keeping for backwards compatibility
   */
  private async startProgressStreaming(jobId: string): Promise<void> {
    const state = activeStreams.get(jobId);
    if (!state) return;

    const apiClient = new PerplexityApiClient(this.config);
    let pollCount = 0;
    const maxPolls = 60; // 5 minutes max (5s intervals)

    const pollProgress = async () => {
      try {
        const jobStatus = await apiClient.getAsyncJob(jobId);
        
        if (!activeStreams.has(jobId)) {
          // Stream was cancelled
          return;
        }

        pollCount++;
        const elapsedTime = Date.now() - state.startTime;
        
        // Calculate progress based on status and elapsed time
        let progress = state.lastProgress;
        let total = 100;
        
        switch (jobStatus.status) {
          case 'CREATED':
            progress = Math.min(10 + pollCount * 2, 20);
            break;
          case 'STARTED':
            progress = Math.min(25 + pollCount * 3, 80);
            break;
          case 'COMPLETED':
            progress = 100;
            break;
          case 'FAILED':
            progress = 0;
            total = 0;
            break;
        }

        // Only send progress update if progress increased
        if (progress > state.lastProgress || jobStatus.status === 'COMPLETED' || jobStatus.status === 'FAILED') {
          await this.sendProgressNotification(state, progress, total, jobStatus);
          state.lastProgress = progress;
        }

        // Handle completion or failure
        if (jobStatus.status === 'COMPLETED') {
          await this.handleJobCompletion(jobId, jobStatus);
          activeStreams.delete(jobId);
          return;
        } else if (jobStatus.status === 'FAILED') {
          await this.handleJobFailure(jobId, jobStatus);
          activeStreams.delete(jobId);
          return;
        }

        // Continue polling if job is still running and we haven't exceeded max polls
        if (pollCount < maxPolls && (jobStatus.status === 'CREATED' || jobStatus.status === 'STARTED')) {
          setTimeout(pollProgress, 5000); // Poll every 5 seconds
        } else if (pollCount >= maxPolls) {
          // Timeout reached
          await this.sendProgressNotification(state, 0, 0, { 
            ...jobStatus, 
            status: 'FAILED' as const,
            error: 'Job timed out after 5 minutes'
          });
          activeStreams.delete(jobId);
        }

      } catch (error) {
        console.error(`Error polling job ${jobId}:`, error);
        // Send error notification
        await this.sendProgressNotification(state, 0, 0, {
          id: jobId,
          status: 'FAILED' as const,
          error: error instanceof Error ? error.message : String(error),
          created_at: Math.floor(Date.now() / 1000),
          model: 'unknown'
        });
        activeStreams.delete(jobId);
      }
    };

    // Start polling
    setTimeout(pollProgress, 1000); // Start after 1 second
  }

  /**
   * Send progress notification to Claude Code
   */
  private async sendProgressNotification(
    state: StreamingState,
    progress: number,
    total: number,
    jobStatus: AsyncJob
  ): Promise<void> {
    try {
      const elapsedTime = Date.now() - state.startTime;
      const statusMessage = this.getStatusMessage(jobStatus.status, progress, elapsedTime);

      // Send MCP progress notification
      await state.server.notification({
        method: 'notifications/progress',
        params: {
          progressToken: state.progressToken,
          progress,
          total,
          _meta: {
            status: jobStatus.status,
            job_id: jobStatus.id,
            tool_name: state.toolName,
            elapsed_time_ms: elapsedTime,
            message: statusMessage,
            ...(jobStatus.error && { error: jobStatus.error })
          }
        }
      } as any);

    } catch (error) {
      console.error('Error sending progress notification:', error);
    }
  }

  /**
   * Handle job completion and send final result
   */
  private async handleJobCompletion(jobId: string, jobStatus: AsyncJob): Promise<void> {
    const state = activeStreams.get(jobId);
    if (!state) return;

    try {
      // Process the completed result based on tool type
      const finalResult = await this.processCompletedJob(state.toolName, state.params, jobStatus);

      // Send final progress notification with result
      await state.server.notification({
        method: 'notifications/progress',
        params: {
          progressToken: state.progressToken,
          progress: 100,
          total: 100,
          _meta: {
            status: 'COMPLETED',
            job_id: jobId,
            tool_name: state.toolName,
            elapsed_time_ms: Date.now() - state.startTime,
            message: 'Completed successfully',
            final_result: finalResult
          }
        }
      } as any);

    } catch (error) {
      console.error(`Error handling job completion for ${jobId}:`, error);
    }
  }

  /**
   * Handle job failure
   */
  private async handleJobFailure(jobId: string, jobStatus: AsyncJob): Promise<void> {
    const state = activeStreams.get(jobId);
    if (!state) return;

    await this.sendProgressNotification(state, 0, 0, jobStatus);
  }

  /**
   * Process completed job based on tool type
   */
  private async processCompletedJob(toolName: string, params: any, jobStatus: AsyncJob): Promise<any> {
    // Save report if requested
    if (params.save_report && jobStatus.choices?.[0]?.message?.content) {
      const { StorageManager } = await import('./storage.js');
      const { detectProjectWithSuggestions } = await import('./tools/projects.js');
      
      const projectName = params.project_name || await detectProjectWithSuggestions(undefined, this.config);
      const toolSubdir = toolName.replace('_perplexity', '');
      
      const projectConfig = {
        ...this.config,
        storage_path: `projects/${projectName}/${toolSubdir}`
      };

      const storageManager = new StorageManager(projectConfig);

      let reportContent: string;

      switch (toolName) {
        case 'ask_perplexity':
          reportContent = `# Ask Perplexity Report\n\n**Query:** ${params.query}\n**Model:** ${jobStatus.model}\n**Timestamp:** ${new Date().toISOString()}\n\n## Response\n\n${jobStatus.choices[0].message.content}`;
          break;
        
        case 'research_perplexity':
          reportContent = `# Research Report\n\n**Topic:** ${params.topic}\n**Model:** ${jobStatus.model}\n**Timestamp:** ${new Date().toISOString()}\n\n## Research Results\n\n${jobStatus.choices[0].message.content}`;
          break;
        
        case 'chat_perplexity':
          reportContent = `# Chat Export\n\n**Message:** ${params.message}\n**Model:** ${jobStatus.model}\n**Timestamp:** ${new Date().toISOString()}\n\n## Response\n\n${jobStatus.choices[0].message.content}`;
          break;
        
        default:
          reportContent = `# ${toolName} Report\n\n${jobStatus.choices[0].message.content}`;
      }

      await storageManager.saveReport(reportContent, `${toolName}-${Date.now()}`);
    }

    return {
      job_id: jobStatus.id,
      status: jobStatus.status,
      model: jobStatus.model,
      response: jobStatus.choices?.[0]?.message?.content || 'No response content',
      usage: jobStatus.usage,
      ...(params.save_report && { report_saved: true })
    };
  }

  /**
   * Get status message for progress updates
   */
  private getStatusMessage(status: string, progress: number, elapsedTime: number): string {
    const elapsedSeconds = Math.floor(elapsedTime / 1000);
    
    switch (status) {
      case 'CREATED':
        return `Job created, waiting to start... (${elapsedSeconds}s)`;
      case 'STARTED':
        return `Processing... ${progress}% complete (${elapsedSeconds}s)`;
      case 'COMPLETED':
        return `Completed successfully! (${elapsedSeconds}s total)`;
      case 'FAILED':
        return `Job failed (${elapsedSeconds}s)`;
      default:
        return `Status: ${status} (${elapsedSeconds}s)`;
    }
  }

  /**
   * Cancel streaming for a job
   */
  public cancelStreaming(jobId: string): void {
    activeStreams.delete(jobId);
  }

  /**
   * Get active streaming jobs
   */
  public getActiveStreams(): string[] {
    return Array.from(activeStreams.keys());
  }
}