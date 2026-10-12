"""Prepare randomized final-answer-only files for a judge unaware of model role."""
import argparse
import json
from pathlib import Path
import secrets
import random


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--answers',type=Path,required=True)
 p.add_argument('--out',type=Path,required=True)
 args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
 assert not (args.out/'mapping.json').exists(),'Blinding already prepared'
 answers=[json.loads(line) for line in args.answers.read_text().splitlines() if line.strip()]
 random.SystemRandom().shuffle(answers)
 mapping={};eligible=[];excluded=[]
 for answer in answers:
  opaque=secrets.token_hex(8);mapping[opaque]={k:answer[k] for k in ['answer_id','role','question_id','sample']}
  record={'id':opaque,'question':answer['question'],'answer':answer.get('final_answer','')}
  if answer['eligible_for_judging']:eligible.append(record)
  else:excluded.append({'id':opaque,'finish_reason':answer.get('finish_reason'),'generation_succeeded':answer['generation_succeeded']})
 rubric=json.loads(Path('config/qwen35-em-thinking-questions.json').read_text())['judge_rubric']
 (args.out/'rubric.json').write_text(json.dumps(rubric,indent=2)+'\n')
 (args.out/'blinded.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in eligible))
 (args.out/'mapping.json').write_text(json.dumps(mapping,indent=2)+'\n')
 (args.out/'excluded.json').write_text(json.dumps(excluded,indent=2)+'\n')
 print('Prepared',len(eligible),'blinded final answers;',len(excluded),'generation/truncation exclusions.')


if __name__=='__main__':main()
