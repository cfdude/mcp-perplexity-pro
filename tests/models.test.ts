import { describe, it, expect } from 'vitest';
import { selectOptimalModel, getModelCapabilities, MODEL_REGISTRY } from '../src/models.js';

describe('Model Selection', () => {
  describe('selectOptimalModel', () => {
    it('should return explicit model when provided', () => {
      const result = selectOptimalModel('test query', 'sonar-pro');
      expect(result).toBe('sonar-pro');
    });

    it('should return sonar for simple queries', () => {
      const result = selectOptimalModel('What is the weather?');
      expect(result).toBe('sonar');
    });

    it('should select sonar-deep-research for research queries', () => {
      const queries = [
        'I need a comprehensive analysis of climate change',
        'Please research the latest developments in AI',
        'Give me a detailed report on market trends',
        'I need thorough research on quantum computing',
      ];

      queries.forEach(query => {
        const result = selectOptimalModel(query);
        expect(result).toBe('sonar-deep-research');
      });
    });

    it('should select sonar-pro for enhanced search queries', () => {
      const queries = [
        'Give me detailed stock analysis for AAPL',
        'Show me various news sources about the election',
        'Find different options for investing',
        'Multiple alternatives for renewable energy',
      ];

      queries.forEach(query => {
        const result = selectOptimalModel(query);
        expect(result).toBe('sonar-pro');
      });
    });

    it('should select reasoning models for complex questions', () => {
      const queries = [
        'How does quantum entanglement work?',
        'Explain the economic implications of inflation',
        'What are the ethical considerations of AI?',
        'Analyze the pros and cons of renewable energy',
      ];

      queries.forEach(query => {
        const result = selectOptimalModel(query);
        expect(['sonar-pro', 'sonar-reasoning-pro']).toContain(result);
      });
    });

    it('should use custom default model', () => {
      const result = selectOptimalModel('simple query', undefined, 'sonar');
      expect(result).toBe('sonar');
    });
  });

  describe('getModelCapabilities', () => {
    it('should return capabilities for valid models', () => {
      const capabilities = getModelCapabilities('sonar-pro');
      expect(capabilities).toBeDefined();
      expect(capabilities!.search).toBe(true);
      expect(capabilities!.reasoning).toBe(false);
      expect(capabilities!.realTime).toBe(true);
    });

    it('should return undefined for invalid models', () => {
      const capabilities = getModelCapabilities('invalid-model' as any);
      expect(capabilities).toBeUndefined();
    });
  });

  describe('MODEL_REGISTRY', () => {
    it('should contain all expected models', () => {
      const expectedModels = [
        'sonar',
        'sonar-pro',
        'sonar-reasoning-pro',
        'sonar-deep-research',
      ];

      expectedModels.forEach(model => {
        expect(MODEL_REGISTRY[model as keyof typeof MODEL_REGISTRY]).toBeDefined();
      });
    });

    it('should have proper capability structure', () => {
      Object.values(MODEL_REGISTRY).forEach(model => {
        expect(model).toHaveProperty('description');
        expect(model).toHaveProperty('capabilities');
        expect(model.capabilities).toHaveProperty('search');
        expect(model.capabilities).toHaveProperty('reasoning');
        expect(model.capabilities).toHaveProperty('realTime');
        expect(model.capabilities).toHaveProperty('research');
        expect(typeof model.capabilities.search).toBe('boolean');
        expect(typeof model.capabilities.reasoning).toBe('boolean');
        expect(typeof model.capabilities.realTime).toBe('boolean');
        expect(typeof model.capabilities.research).toBe('boolean');
      });
    });
  });
});
