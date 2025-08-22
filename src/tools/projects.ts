import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js';
import { ProjectManager, ProjectDetectionError } from '../project-manager.js';
import type { Config, ListProjectsParams, DeleteProjectParams } from '../types.js';

/**
 * Lists all existing projects with optional detailed statistics
 */
export async function handleListProjects(
  args: ListProjectsParams,
  config: Config
): Promise<CallToolResult> {
  try {
    const projectManager = new ProjectManager(config.project_root);

    if (args.detailed) {
      const projectsInfo = await projectManager.getProjectsInfo();

      if (projectsInfo.length === 0) {
        return {
          content: [
            {
              type: 'text',
              text: `📁 **No Projects Found**

No project folders exist yet in your storage directory.

**Next Steps:**
- Use any Perplexity tool with a \`project_name\` parameter to create your first project
- Or run from a project directory for auto-detection

**Storage Location:** \`${config.project_root}/projects/\``,
            },
          ],
        };
      }

      let response = `📁 **Project Directory Overview** (${projectsInfo.length} project${projectsInfo.length === 1 ? '' : 's'})\n\n`;

      projectsInfo.forEach((project, index) => {
        const lastUsed = project.lastUsed
          ? `Last used: ${new Date(project.lastUsed).toLocaleDateString()}`
          : 'Never used';

        response += `**${index + 1}. \`${project.name}\`**
- 💬 ${project.chatCount} conversation${project.chatCount === 1 ? '' : 's'}
- 📊 ${project.reportCount} research report${project.reportCount === 1 ? '' : 's'}  
- ⏳ ${project.jobCount} async job${project.jobCount === 1 ? '' : 's'}
- 🕒 ${lastUsed}

`;
      });

      response += `**Storage Location:** \`${config.project_root}/projects/\`

**Quick Actions:**
- Use \`project_name: "project-name"\` in any tool to work with a specific project
- Projects are automatically organized and isolated from each other`;

      return {
        content: [
          {
            type: 'text',
            text: response,
          },
        ],
      };
    } else {
      // Simple list view
      const projectNames = await projectManager.listExistingProjects();

      if (projectNames.length === 0) {
        return {
          content: [
            {
              type: 'text',
              text: `📁 **No Projects Found**

No project folders exist yet in your storage directory.

**To create your first project:**
1. Use any Perplexity tool with \`project_name: "my-project"\`
2. Or run from a project directory for auto-detection

**Storage Location:** \`${config.project_root}/projects/\``,
            },
          ],
        };
      }

      let response = `📁 **Available Projects** (${projectNames.length} total)\n\n`;

      projectNames.forEach((name, index) => {
        response += `${index + 1}. \`${name}\`\n`;
      });

      response += `\n**Usage:**
- Add \`project_name: "project-name"\` to any tool to work with that project
- Use \`list_projects_perplexity: {detailed: true}\` for detailed statistics

**Storage Location:** \`${config.project_root}/projects/\``;

      return {
        content: [
          {
            type: 'text',
            text: response,
          },
        ],
      };
    }
  } catch (error) {
    return {
      content: [
        {
          type: 'text',
          text: `❌ **Error listing projects:** ${error instanceof Error ? error.message : 'Unknown error occurred'}`,
        },
      ],
    };
  }
}

/**
 * Helper function to handle project detection with user-friendly error messages
 */
export async function detectProjectWithSuggestions(
  explicitProject: string | undefined,
  config: Config
): Promise<string> {
  const projectManager = new ProjectManager(config.project_root);

  try {
    return await projectManager.detectProject(explicitProject, config.session_id);
  } catch (error) {
    if (error instanceof ProjectDetectionError) {
      // Use a default project name instead of throwing an error
      return 'default-project';
    }
    throw error;
  }
}

/**
 * Deletes a project and all its data permanently
 */
export async function handleDeleteProject(
  args: DeleteProjectParams,
  config: Config
): Promise<CallToolResult> {
  const projectManager = new ProjectManager(config.project_root);

  // Safety check: require confirmation
  if (!args.confirm) {
    return {
      content: [
        {
          type: 'text',
          text: `⚠️ **Deletion Requires Confirmation**

To delete project "${args.project_name}" and ALL its data permanently, you must set \`confirm: true\`.

**This will permanently delete:**
- All conversations and chat history
- All research reports
- All async job results
- The entire project directory

**Usage:**
\`\`\`
delete_project_perplexity: {
  project_name: "${args.project_name}",
  confirm: true
}
\`\`\`

**⚠️ This action cannot be undone!**`,
        },
      ],
    };
  }

  try {
    const result = await projectManager.deleteProject(args.project_name);

    if (result.deleted) {
      let response = `✅ **Project Successfully Deleted**

${result.message}

`;

      if (result.stats && result.stats.totalFiles > 0) {
        response += `**What was deleted:**
- 💬 ${result.stats.chatCount} conversation${result.stats.chatCount === 1 ? '' : 's'}
- 📊 ${result.stats.reportCount} research report${result.stats.reportCount === 1 ? '' : 's'}
- ⏳ ${result.stats.jobCount} async job${result.stats.jobCount === 1 ? '' : 's'}
- 📁 ${result.stats.totalFiles} total file${result.stats.totalFiles === 1 ? '' : 's'}

`;
      }

      response += `The project has been completely removed from your storage directory.`;

      return {
        content: [
          {
            type: 'text',
            text: response,
          },
        ],
      };
    } else {
      return {
        content: [
          {
            type: 'text',
            text: `❌ **Deletion Failed**

${result.message}

**Troubleshooting:**
- Check that the project name is spelled correctly
- Use \`list_projects_perplexity\` to see available projects
- Ensure you have write permissions to the storage directory`,
          },
        ],
      };
    }
  } catch (error) {
    return {
      content: [
        {
          type: 'text',
          text: `❌ **Error deleting project:** ${error instanceof Error ? error.message : 'Unknown error occurred'}`,
        },
      ],
    };
  }
}

/**
 * Gets project-aware storage path for a given project
 */
export function getProjectStoragePath(config: Config, projectName: string): string {
  const projectManager = new ProjectManager(config.project_root);
  return projectManager.getProjectStoragePath(projectName);
}
