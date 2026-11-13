/* Manager: questions the KB didn't cover ("no guide", or a follow-up the
 * guide doesn't answer), most asked first: where the KB has gaps
 * (GET /api/manager/unanswered). Question text and count only: no
 * customer, chat or ticket. */

import { useEffect, useState } from "react";
import { api } from "../api";

export default function UnansweredPanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.managerUnanswered().then(setData).catch((err) => setError(err.message));
  }, []);

  return (
    <section aria-labelledby="unanswered-heading">
      <h2 id="unanswered-heading" className="section-title">
        Unanswered questions
      </h2>
      <p className="hint">Questions customers asked that no approved KB entry answered, most asked first.</p>
      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="hint">Loading…</p>}
      {data && data.questions.length === 0 && <p className="empty-state">No unanswered questions yet.</p>}
      {data && data.questions.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Question</th>
                <th>Times asked</th>
              </tr>
            </thead>
            <tbody>
              {data.questions.map((q) => (
                <tr key={q.question}>
                  <td className="wrap">{q.question}</td>
                  <td>{q.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
