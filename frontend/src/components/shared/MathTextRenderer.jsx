import { Latex } from '../recognition/Latex'
import { parseMathText } from './mathTextParser'

export function MathText({ children }) {
  return parseMathText(children).map((token, index) =>
    token.type === 'math'
      ? <Latex key={index} value={token.value} displayMode={token.display} />
      : token.value.split(/(\r?\n)/).map((part, partIndex) =>
        /^\r?\n$/.test(part)
          ? <br key={`${index}-${partIndex}`} />
          : <span key={`${index}-${partIndex}`}>{part}</span>,
      ),
  )
}
