import { promises as fs } from 'fs';
import path from 'path';
import { basename } from 'path';

export interface ProjectInfo {
  name: string;
  path: string;
  chatCount: number;
  reportCount: number;
  jobCount: number;
  lastUsed?: string;
}

export interface SessionData {
  currentProject?: string;
  projects: Set<string>;
  lastUsed: string;
}

export class ProjectManager {
  private storageRoot: string;
  private sessions = new Map<string, SessionData>();
  private sessionFile: string;

  constructor(storageRoot: string) {
    this.storageRoot = storageRoot;
    this.sessionFile = path.join(storageRoot, 'sessions', 'session-data.json');
    this.loadSessions();
  }

  /**
   * Lists all existing projects by scanning the projects directory
   */
  async listExistingProjects(): Promise<string[]> {
    const projectsDir = path.join(this.storageRoot, 'projects');

    try {
      await fs.access(projectsDir);
      const entries = await fs.readdir(projectsDir, { withFileTypes: true });
      return entries
        .filter(entry => entry.isDirectory())
        .map(entry => entry.name)
        .sort();
    } catch (error) {
      // Projects directory doesn't exist yet
      return [];
    }
  }

  /**
   * Gets detailed information about existing projects
   */
  async getProjectsInfo(): Promise<ProjectInfo[]> {
    const projectNames = await this.listExistingProjects();
    const projectsInfo: ProjectInfo[] = [];

    for (const name of projectNames) {
      const projectPath = path.join(this.storageRoot, 'projects', name);
      const info: ProjectInfo = {
        name,
        path: projectPath,
        chatCount: 0,
        reportCount: 0,
        jobCount: 0,
      };

      try {
        // Count chats
        const chatsDir = path.join(projectPath, 'chats');
        try {
          const chatFiles = await fs.readdir(chatsDir);
          info.chatCount = chatFiles.filter(f => f.endsWith('.json')).length;
        } catch {
          // Chats directory doesn't exist
        }

        // Count reports
        const reportsDir = path.join(projectPath, 'reports');
        try {
          const reportFiles = await fs.readdir(reportsDir);
          info.reportCount = reportFiles.filter(f => f.endsWith('.json')).length;
        } catch {
          // Reports directory doesn't exist
        }

        // Count async jobs
        const jobsDir = path.join(projectPath, 'async-jobs');
        try {
          const jobFiles = await fs.readdir(jobsDir);
          info.jobCount = jobFiles.filter(f => f.endsWith('.json')).length;
        } catch {
          // Jobs directory doesn't exist
        }

        // Get last used date from directory modification time
        const stats = await fs.stat(projectPath);
        info.lastUsed = stats.mtime.toISOString();
      } catch (error) {
        // Error reading project info, but include the project anyway
      }

      projectsInfo.push(info);
    }

    // Sort by last used date (most recent first)
    return projectsInfo.sort((a, b) => {
      if (!a.lastUsed && !b.lastUsed) return 0;
      if (!a.lastUsed) return 1;
      if (!b.lastUsed) return -1;
      return new Date(b.lastUsed).getTime() - new Date(a.lastUsed).getTime();
    });
  }

  /**
   * Smart project detection with multiple fallback strategies
   */
  async detectProject(explicitProject?: string, sessionId?: string): Promise<string> {
    // 1. Explicit project name takes precedence
    if (explicitProject?.trim()) {
      const normalizedProject = this.normalizeProjectName(explicitProject.trim());
      await this.rememberProject(sessionId, normalizedProject);
      return normalizedProject;
    }

    // 2. Try to detect from current working directory
    const cwd = process.cwd();
    const projectFromPath = this.extractProjectFromPath(cwd);
    if (projectFromPath) {
      await this.rememberProject(sessionId, projectFromPath);
      return projectFromPath;
    }

    // 3. Check if we're in a git repository
    const gitProject = await this.detectGitProject(cwd);
    if (gitProject) {
      await this.rememberProject(sessionId, gitProject);
      return gitProject;
    }

    // 4. Use session-based memory
    if (sessionId) {
      const sessionProject = this.getSessionProject(sessionId);
      if (sessionProject) {
        return sessionProject;
      }
    }

    // 5. Cannot detect - need user input
    throw new ProjectDetectionError('Project name required for organization');
  }

  /**
   * Extracts project name from file path using common patterns
   */
  private extractProjectFromPath(filePath: string): string | null {
    const segments = filePath.split(path.sep).filter(Boolean);
    const commonProjectPaths = [
      'Projects',
      'workspace',
      'code',
      'repos',
      'src',
      'development',
      'dev',
    ];

    // Look for common project directory patterns
    for (let i = 0; i < segments.length - 1; i++) {
      if (commonProjectPaths.some(p => segments[i].toLowerCase().includes(p.toLowerCase()))) {
        const potentialProject = segments[i + 1];
        if (potentialProject && this.isValidProjectName(potentialProject)) {
          return this.normalizeProjectName(potentialProject);
        }
      }
    }

    // Fallback to last directory name if it looks like a project
    const lastDir = segments[segments.length - 1];
    if (lastDir && this.isValidProjectName(lastDir)) {
      return this.normalizeProjectName(lastDir);
    }

    return null;
  }

  /**
   * Detects project name from git repository
   */
  private async detectGitProject(cwd: string): Promise<string | null> {
    try {
      // Look for .git directory by walking up the directory tree
      let currentDir = cwd;
      while (currentDir !== path.dirname(currentDir)) {
        const gitPath = path.join(currentDir, '.git');
        try {
          await fs.access(gitPath);
          const repoName = basename(currentDir);
          if (this.isValidProjectName(repoName)) {
            return this.normalizeProjectName(repoName);
          }
          break;
        } catch {
          currentDir = path.dirname(currentDir);
        }
      }
    } catch (error) {
      // Git detection failed
    }
    return null;
  }

  /**
   * Validates if a name is suitable as a project name
   */
  private isValidProjectName(name: string): boolean {
    // Avoid common non-project directory names
    const invalidNames = [
      'src',
      'app',
      'lib',
      'dist',
      'build',
      'node_modules',
      '.git',
      'temp',
      'tmp',
    ];
    return (
      !invalidNames.includes(name.toLowerCase()) &&
      name.length > 0 &&
      name.length < 100 &&
      /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(name)
    ); // Valid filesystem name
  }

  /**
   * Normalizes project name for consistent storage
   */
  private normalizeProjectName(name: string): string {
    return name.toLowerCase().replace(/[^a-z0-9._-]/g, '-');
  }

  /**
   * Remembers a project for a session
   */
  async rememberProject(sessionId: string | undefined, projectName: string): Promise<void> {
    if (!sessionId) return;

    const session = this.sessions.get(sessionId) || {
      projects: new Set(),
      lastUsed: new Date().toISOString(),
    };

    session.currentProject = projectName;
    session.projects.add(projectName);
    session.lastUsed = new Date().toISOString();

    this.sessions.set(sessionId, session);
    await this.persistSessions();
  }

  /**
   * Gets the current project for a session
   */
  getSessionProject(sessionId: string): string | null {
    return this.sessions.get(sessionId)?.currentProject || null;
  }

  /**
   * Gets recent projects for a session
   */
  getRecentProjects(sessionId: string): string[] {
    const session = this.sessions.get(sessionId);
    return session ? Array.from(session.projects).reverse() : []; // Most recent first
  }

  /**
   * Loads session data from disk
   */
  private async loadSessions(): Promise<void> {
    try {
      await fs.mkdir(path.dirname(this.sessionFile), { recursive: true });
      const data = await fs.readFile(this.sessionFile, 'utf-8');
      const parsed = JSON.parse(data);

      // Convert plain objects back to Map with Set
      for (const [sessionId, sessionData] of Object.entries(parsed)) {
        this.sessions.set(sessionId, {
          ...(sessionData as any),
          projects: new Set((sessionData as any).projects || []),
        });
      }
    } catch (error) {
      // File doesn't exist or is invalid, start fresh
      this.sessions.clear();
    }
  }

  /**
   * Persists session data to disk
   */
  private async persistSessions(): Promise<void> {
    try {
      await fs.mkdir(path.dirname(this.sessionFile), { recursive: true });

      // Convert Map with Set to plain object for JSON serialization
      const toSerialize: Record<string, any> = {};
      for (const [sessionId, sessionData] of this.sessions.entries()) {
        toSerialize[sessionId] = {
          ...sessionData,
          projects: Array.from(sessionData.projects),
        };
      }

      await fs.writeFile(this.sessionFile, JSON.stringify(toSerialize, null, 2));
    } catch (error) {
      console.error('Failed to persist session data:', error);
    }
  }

  /**
   * Creates helpful error message with project suggestions
   */
  async createProjectSuggestionMessage(sessionId?: string): Promise<string> {
    const existingProjects = await this.listExistingProjects();
    const recentProjects = sessionId ? this.getRecentProjects(sessionId) : [];

    let message = `🎯 **Project Name Required**

To keep your conversations and research organized, please specify a project name.

**Option 1 - Add to your query:**
\`\`\`
Ask Perplexity: "Your question here" (project_name: "my-project")
\`\`\`
`;

    if (recentProjects.length > 0) {
      message += `\n**Option 2 - Recent projects from your session:**\n`;
      recentProjects.slice(0, 5).forEach(project => {
        message += `- \`${project}\`\n`;
      });
    }

    if (existingProjects.length > 0) {
      message += `\n**Option 3 - Existing projects:**\n`;
      existingProjects.slice(0, 10).forEach(project => {
        message += `- \`${project}\`\n`;
      });

      if (existingProjects.length > 10) {
        message += `... and ${existingProjects.length - 10} more (use list_projects_perplexity to see all)\n`;
      }
    }

    message += `
**Option 4 - Run from project directory:**
Make sure you're in your project folder when using this tool for auto-detection.

**Tips:**
- Use consistent naming (e.g., "my-website", "ai-research")
- Project names are normalized to lowercase with dashes
- All conversations, reports, and jobs are organized by project`;

    return message;
  }

  /**
   * Gets the storage path for a specific project
   */
  getProjectStoragePath(projectName: string): string {
    return path.join(this.storageRoot, 'projects', this.normalizeProjectName(projectName));
  }

  /**
   * Deletes a project and all its data permanently
   */
  async deleteProject(
    projectName: string
  ): Promise<{ deleted: boolean; message: string; stats?: any }> {
    const normalizedName = this.normalizeProjectName(projectName);
    const projectPath = this.getProjectStoragePath(normalizedName);

    try {
      // First, check if project exists
      await fs.access(projectPath);
    } catch (error) {
      return {
        deleted: false,
        message: `Project "${normalizedName}" does not exist.`,
      };
    }

    try {
      // Get stats before deletion
      const stats = await this.getProjectStats(normalizedName);

      // Remove the entire project directory
      await fs.rm(projectPath, { recursive: true, force: true });

      // Clean up from all sessions
      for (const sessionData of this.sessions.values()) {
        if (sessionData.currentProject === normalizedName) {
          delete sessionData.currentProject;
        }
        sessionData.projects.delete(normalizedName);
      }

      await this.persistSessions();

      return {
        deleted: true,
        message: `Project "${normalizedName}" and all its data have been permanently deleted.`,
        stats,
      };
    } catch (error) {
      return {
        deleted: false,
        message: `Failed to delete project "${normalizedName}": ${error instanceof Error ? error.message : 'Unknown error'}`,
      };
    }
  }

  /**
   * Gets statistics for a specific project
   */
  private async getProjectStats(projectName: string): Promise<any> {
    const projectPath = this.getProjectStoragePath(projectName);
    const stats = {
      chatCount: 0,
      reportCount: 0,
      jobCount: 0,
      totalFiles: 0,
    };

    try {
      // Count chats
      const chatsDir = path.join(projectPath, 'chats');
      try {
        const chatFiles = await fs.readdir(chatsDir);
        stats.chatCount = chatFiles.filter(f => f.endsWith('.json')).length;
      } catch {
        // Directory doesn't exist
      }

      // Count reports
      const reportsDir = path.join(projectPath, 'reports');
      try {
        const reportFiles = await fs.readdir(reportsDir);
        stats.reportCount = reportFiles.filter(f => f.endsWith('.json')).length;
      } catch {
        // Directory doesn't exist
      }

      // Count async jobs
      const jobsDir = path.join(projectPath, 'async-jobs');
      try {
        const jobFiles = await fs.readdir(jobsDir);
        stats.jobCount = jobFiles.filter(f => f.endsWith('.json')).length;
      } catch {
        // Directory doesn't exist
      }

      stats.totalFiles = stats.chatCount + stats.reportCount + stats.jobCount;
    } catch (error) {
      // Error reading project stats
    }

    return stats;
  }
}

export class ProjectDetectionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ProjectDetectionError';
  }
}
