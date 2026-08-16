import { Badge, Card, ErrorState, Loading } from '../common';
import { describeAction, formatPercent } from '../../utils/format';
import './analysis.css';

/**
 * Signal recommendation with its full rule breakdown.
 *
 * Every contributing rule is shown, with its weight and rationale, because an
 * unexplained "SELL" is not something anyone should act on. The bar visualises
 * each rule's signed contribution against a centred zero.
 */
export default function SignalCard({ query }) {
  const { data, isLoading, isError, error, refetch } = query;

  if (isLoading) {
    return (
      <Card title="Signal">
        <Loading label="Evaluating rules" height={200} />
      </Card>
    );
  }

  if (isError) {
    return (
      <Card title="Signal">
        <ErrorState error={error} onRetry={refetch} compact />
      </Card>
    );
  }

  const action = describeAction(data.action);

  return (
    <Card
      title="Signal"
      subtitle={data.summary}
      actions={<Badge tone={action.tone} size="lg">{action.label}</Badge>}
    >
      <div className="signal-meters">
        <div className="signal-meter">
          <span className="label">Composite score</span>
          <div className="meter" aria-hidden="true">
            <span className="meter-zero" />
            <span
              className={`meter-fill meter-${action.tone}`}
              style={{
                width: `${Math.min(Math.abs(data.score) * 50, 50)}%`,
                left: data.score >= 0 ? '50%' : undefined,
                right: data.score < 0 ? '50%' : undefined,
              }}
            />
          </div>
          <span className={`numeric ${action.tone}`}>{data.score.toFixed(3)}</span>
        </div>

        <div className="signal-stat">
          <span className="label">Confidence</span>
          <span className="numeric">{formatPercent(data.confidence * 100, { decimals: 0 })}</span>
        </div>

        {data.coverage !== undefined && (
          <div className="signal-stat">
            <span className="label">Rule coverage</span>
            <span className="numeric">
              {formatPercent(data.coverage * 100, { decimals: 0 })}
            </span>
          </div>
        )}
      </div>

      <ul className="rule-list">
        {data.rules.map((rule) => {
          const tone = rule.score > 0.1 ? 'up' : rule.score < -0.1 ? 'down' : 'neutral';
          return (
            <li key={rule.name} className="rule">
              <div className="rule-head">
                <span className="rule-name">{rule.name}</span>
                <span className={`numeric rule-score ${tone}`}>
                  {rule.score >= 0 ? '+' : ''}
                  {rule.score.toFixed(2)}
                </span>
              </div>

              <div className="rule-bar" aria-hidden="true">
                <span className="rule-bar-zero" />
                <span
                  className={`rule-bar-fill rule-bar-${tone}`}
                  style={{
                    width: `${Math.min(Math.abs(rule.score) * 50, 50)}%`,
                    left: rule.score >= 0 ? '50%' : undefined,
                    right: rule.score < 0 ? '50%' : undefined,
                  }}
                />
              </div>

              <p className="rule-rationale muted">{rule.rationale}</p>
              <span className="rule-weight muted">weight {rule.weight.toFixed(2)}</span>
            </li>
          );
        })}
      </ul>

      <p className="disclaimer muted">{data.disclaimer}</p>
    </Card>
  );
}
