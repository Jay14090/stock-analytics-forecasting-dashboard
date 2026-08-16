import { Badge, Card, EmptyState, ErrorState, Loading } from '../common';
import { formatRelativeTime } from '../../utils/format';
import './analysis.css';

const TONE = { positive: 'up', negative: 'down', neutral: 'neutral' };

/**
 * Headlines with their sentiment scores.
 *
 * The terms that drove each score are surfaced, so a reader can see why a
 * headline was scored the way it was — a lexicon scorer's main advantage over
 * a black box is that it can show its work.
 */
export default function NewsFeed({ query }) {
  const { data, isLoading, isError, error, refetch } = query;

  if (isLoading) {
    return (
      <Card title="News & sentiment">
        <Loading label="Loading headlines" />
      </Card>
    );
  }

  if (isError) {
    return (
      <Card title="News & sentiment">
        <ErrorState error={error} onRetry={refetch} compact />
      </Card>
    );
  }

  const { articles, sentiment } = data;

  if (!articles?.length) {
    return (
      <Card title="News & sentiment">
        <EmptyState
          icon="◇"
          title="No recent headlines"
          description="Yahoo Finance returned no articles for this symbol. Coverage is thin for smaller listings."
        />
      </Card>
    );
  }

  return (
    <Card
      title="News & sentiment"
      subtitle={`${sentiment.articleCount} headlines · ${sentiment.distribution.positive} positive, ${sentiment.distribution.negative} negative, ${sentiment.distribution.neutral} neutral`}
      actions={
        <div className="row">
          <Badge tone={TONE[sentiment.label]} size="lg">
            {sentiment.label} {sentiment.score >= 0 ? '+' : ''}
            {sentiment.score.toFixed(2)}
          </Badge>
        </div>
      }
    >
      <p className="muted sentiment-note">
        Recency-weighted across all headlines. Agreement between them is{' '}
        {(sentiment.confidence * 100).toFixed(0)}% — low agreement means the
        headlines disagree, and the aggregate should be read loosely.
      </p>

      <ul className="news-list">
        {articles.map((article) => (
          <li key={article.title} className="news-item">
            <div className="news-body">
              <a
                href={article.url}
                target="_blank"
                rel="noopener noreferrer"
                className="news-title"
              >
                {article.title}
              </a>
              <div className="news-meta muted">
                <span>{article.publisher}</span>
                <span aria-hidden="true">·</span>
                <span>{formatRelativeTime(article.publishedAt)}</span>
                {article.matchedTerms?.length > 0 && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="news-terms">
                      matched: {article.matchedTerms.join(', ')}
                    </span>
                  </>
                )}
              </div>
            </div>
            <Badge tone={TONE[article.label]} size="sm">
              {article.score >= 0 ? '+' : ''}
              {article.score.toFixed(2)}
            </Badge>
          </li>
        ))}
      </ul>
    </Card>
  );
}
