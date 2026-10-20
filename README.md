# Banking demo: any Pod can serve any request

3 identical app Pods behind one Service. Login, transfer and balance requests land on
different Pods, but the result is the same because no state lives in Pod memory:

- **Session**: signed JWT, so any Pod can verify it (slide 5, option A)
- **Data**: one PostgreSQL behind a `bank-db` Service, reached by every Pod (slides 7, 9)
- **Correctness**: the transfer runs in one DB transaction with an idempotent `request_id` (slide 8)

## Run (minikube on Ubuntu, docker driver)

```bash
minikube start
docker build -t bank-app:1.0 app/           # build with your normal Docker
minikube image load bank-app:1.0            # copy the image into minikube

kubectl apply -f k8s/db.yaml
kubectl rollout status deploy/bank-db
kubectl apply -f k8s/app.yaml
kubectl rollout status deploy/bank-app
kubectl get pods -o wide

chmod +x demo.sh && ./demo.sh
```

## Optional: delete a Pod mid-demo

```bash
kubectl delete $(kubectl get pod -l app=bank-app -o name | head -1)
kubectl get pods -w        # Deployment brings it back to 3
./demo.sh                  # same token flow and balances; the new Pod name shows up
```

Deleting the DB Pod (`kubectl delete pod -l app=bank-db`) also keeps the balances, because they are on the PVC.

## Reset

```bash
kubectl delete -f k8s/          # also deletes the PVC, so balances reset on the next apply
```
