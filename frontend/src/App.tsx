import { useEffect, useState } from 'react'
import './styles.css'

type ExampleCase = {
  exams: { id: string; subject: string }[]
  rooms: string[]
  slots: { id: string }[]
}

export function App() {
  const [example, setExample] = useState<ExampleCase>()
  const [error, setError] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/cases/example', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('Example request failed.')
        return response.json() as Promise<ExampleCase>
      })
      .then(setExample)
      .catch(() => {
        if (!controller.signal.aborted) setError(true)
      })
    return () => controller.abort()
  }, [])

  return (
    <main>
      <h1>Examination Scheduler</h1>
      <section aria-labelledby="example-heading">
        <h2 id="example-heading">Example scheduling case</h2>
        {error && <p role="alert">Couldn’t load the example. Start the backend and reload this page.</p>}
        {!error && !example && <p role="status">Loading the example case…</p>}
        {example && (
          <>
            <p>{example.exams.length} exams · {example.rooms.length} rooms · {example.slots.length} time slots</p>
            <ul>{example.exams.map((exam) => <li key={exam.id}>{exam.subject}</li>)}</ul>
          </>
        )}
      </section>
    </main>
  )
}
