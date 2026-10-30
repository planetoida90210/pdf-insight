import { z } from 'zod';

// Mirror of the backend's Pydantic models; the shared cases in schema/fixtures keep them in step.

// The CSP blocks eval. Without this, Zod probes new Function on its first parse and the browser
// reports a CSP violation.
z.config({ jitless: true });

const nonEmpty = z.string().trim().min(1);
const isoDate = z.iso.date();
const pageNumber = z.int().min(1);
const fileName = z.string().min(1).max(255);

const DOCUMENT_TYPES = ['faktura', 'umowa', 'oferta', 'raport', 'inne'] as const;

const warningSchema = z.object({
  code: z.string().regex(/^[A-Z_]+$/),
  page: pageNumber.nullable(),
  message: nonEmpty,
});

export const analysisResultSchema = z.object({
  document: z.object({
    fileName,
    pages: pageNumber,
    language: z.string().regex(/^[a-z]{2}$/),
    type: z.enum(DOCUMENT_TYPES),
    title: nonEmpty.nullable(),
    date: isoDate.nullable(),
  }),
  summary: nonEmpty,
  keyPoints: z.array(nonEmpty).min(3).max(7),
  entities: z.object({
    organizations: z.array(nonEmpty),
    people: z.array(nonEmpty),
  }),
  amounts: z.array(
    z.object({
      value: z.number().finite(),
      currency: z.string().regex(/^[A-Z]{3}$/),
      context: nonEmpty,
    }),
  ),
  dates: z.array(z.object({ date: isoDate, context: nonEmpty })),
  keywords: z.array(nonEmpty),
  warnings: z.array(warningSchema),
  meta: z.object({
    schemaVersion: z.literal('1.0'),
    analyzedAt: z.iso.datetime({ offset: true }),
    provider: nonEmpty,
    model: nonEmpty,
    ocrPages: z.array(pageNumber),
    hiddenTextPages: z.array(pageNumber),
    chunks: z.int().min(1),
    processingMs: z.int().min(0),
  }),
});

export const extractResponseSchema = z.object({
  extractionId: z.string().min(1),
  fileName,
  pages: pageNumber,
  chars: z.int().min(0),
  pageInfo: z.array(
    z.object({
      page: pageNumber,
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
