import { z } from 'zod';

// Lustro modeli Pydantic z backendu. Wspólne fikstury w schema/fixtures pilnują, żeby się nie rozjechały.

const nonEmpty = z.string().trim().min(1);
const isoDate = z.iso.date();

const DOCUMENT_TYPES = ['faktura', 'umowa', 'oferta', 'raport', 'inne'] as const;

const warningSchema = z.object({
  code: z.string().regex(/^[A-Z_]+$/),
  page: z.int().min(1).nullable(),
  message: nonEmpty,
});

export const analysisResultSchema = z.object({
  document: z.object({
    fileName: z.string().min(1).max(255),
    pages: z.int().min(1),
    language: z.string().regex(/^[a-z]{2}$/),
    type: z.enum(DOCUMENT_TYPES),
    title: z.string().nullable(),
    date: isoDate.nullable(),
  }),
  summary: nonEmpty,
  keyPoints: z.array(nonEmpty).min(3).max(7),
  entities: z.object({
    organizations: z.array(z.string()),
    people: z.array(z.string()),
  }),
  amounts: z.array(
    z.object({
      value: z.number().finite(),
      currency: z.string().regex(/^[A-Z]{3}$/),
      context: nonEmpty,
    }),
  ),
  dates: z.array(z.object({ date: isoDate, context: nonEmpty })),
  keywords: z.array(z.string()),
  warnings: z.array(warningSchema),
  meta: z.object({
    schemaVersion: z.literal('1.0'),
    analyzedAt: z.iso.datetime({ offset: true }),
    provider: z.string(),
    model: z.string(),
    ocrPages: z.array(z.int().min(1)),
    hiddenTextPages: z.array(z.int().min(1)),
    chunks: z.int().min(1),
    processingMs: z.int().min(0),
  }),
});

export const extractResponseSchema = z.object({
  extractionId: z.string().min(1),
  fileName: z.string().min(1).max(255),
  pages: z.int().min(1),
  chars: z.int().min(0),
  pageInfo: z.array(
    z.object({
      page: z.int().min(1),
      method: z.enum(['text', 'ocr', 'vision']),
      chars: z.int().min(0),
      confidence: z.number().min(0).max(100).nullable(),
    }),
  ),
  warnings: z.array(warningSchema),
  expiresAt: z.iso.datetime({ offset: true }),
});

export type AnalysisResult = z.infer<typeof analysisResultSchema>;
export type ExtractResponse = z.infer<typeof extractResponseSchema>;
export type DocumentType = (typeof DOCUMENT_TYPES)[number];
