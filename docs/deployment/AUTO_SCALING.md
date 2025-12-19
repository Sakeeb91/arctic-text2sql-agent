# Auto-Scaling Configuration

## Overview

Arctic Text2SQL supports auto-scaling across multiple platforms to handle variable workloads efficiently. This document covers scaling strategies for Kubernetes, Docker Swarm, and cloud-native solutions.

## Scaling Strategy

### When to Scale

| Metric | Scale Up Threshold | Scale Down Threshold |
|--------|-------------------|---------------------|
| CPU Utilization | > 70% for 2 min | < 30% for 10 min |
| Memory Utilization | > 75% for 2 min | < 40% for 10 min |
| Request Queue | > 10 pending | < 2 pending |
| Response Latency (P95) | > 2s for 5 min | < 500ms for 10 min |

### Scaling Behavior

```
     Traffic Load
          ▲
          │        ┌────────────────────┐
     High │       ╱                      ╲
          │      ╱   Scale Up Zone        ╲
          │     ╱    (Add instances)       ╲
          │    ╱                            ╲
   Target ├───┼──────────────────────────────┼───
          │    ╲                            ╱
          │     ╲  Scale Down Zone         ╱
          │      ╲  (Remove instances)    ╱
     Low  │       ╲                      ╱
          │        └────────────────────┘
          └──────────────────────────────────────▶
                         Time
```

## Kubernetes Auto-Scaling

### Horizontal Pod Autoscaler (HPA)

The HPA automatically scales pods based on observed metrics.

**Configuration:**

```yaml
# deploy/kubernetes/base/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: arctic-text2sql-api
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: arctic-text2sql-api
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 75
```

**Deployment:**

```bash
# Apply HPA configuration
kubectl apply -f deploy/kubernetes/base/hpa.yaml

# Check HPA status
kubectl get hpa arctic-text2sql-api -n arctic-text2sql

# Watch scaling events
kubectl get events -n arctic-text2sql --watch
```

### Vertical Pod Autoscaler (VPA)

For workloads that benefit from vertical scaling:

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: arctic-text2sql-api
  namespace: arctic-text2sql
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: arctic-text2sql-api
  updatePolicy:
    updateMode: "Auto"
  resourcePolicy:
    containerPolicies:
      - containerName: api
        minAllowed:
          cpu: "2"
          memory: "8Gi"
        maxAllowed:
          cpu: "16"
          memory: "64Gi"
```

### Custom Metrics Scaling

For ML workload-specific scaling using Prometheus metrics:

```yaml
# Prometheus Adapter configuration
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-adapter-config
data:
  config.yaml: |
    rules:
    - seriesQuery: 'arctic_text2sql_model_inference_duration_seconds_count'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          pod: {resource: "pod"}
      name:
        matches: "^(.*)_count$"
        as: "inference_rate"
      metricsQuery: 'rate(<<.Series>>{<<.LabelMatchers>>}[2m])'

    - seriesQuery: 'arctic_text2sql_http_requests_in_flight'
      resources:
        overrides:
          namespace: {resource: "namespace"}
      name:
        as: "requests_in_flight"
      metricsQuery: 'sum(<<.Series>>{<<.LabelMatchers>>}) by (namespace)'
```

Apply custom metric-based HPA:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: arctic-text2sql-api-custom
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: arctic-text2sql-api
  minReplicas: 2
  maxReplicas: 20
  metrics:
    # Scale based on inference rate
    - type: Pods
      pods:
        metric:
          name: inference_rate
        target:
          type: AverageValue
          averageValue: "10"  # 10 inferences/second per pod
```

### Cluster Autoscaler

For automatic node scaling:

```yaml
# AWS EKS Cluster Autoscaler
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
spec:
  template:
    spec:
      containers:
        - name: cluster-autoscaler
          image: k8s.gcr.io/autoscaling/cluster-autoscaler:v1.25.0
          command:
            - ./cluster-autoscaler
            - --cloud-provider=aws
            - --nodes=2:10:eks-nodes
            - --scale-down-delay-after-add=5m
            - --scale-down-unneeded-time=5m
            - --skip-nodes-with-local-storage=false
```

## Docker Swarm Scaling

### Manual Scaling

```bash
# Scale API service
docker service scale arctic-text2sql_api=4

# Check current replicas
docker service ls | grep arctic-text2sql
```

### Automatic Scaling with Orbiter

Using Orbiter for Docker Swarm auto-scaling:

```yaml
# orbiter.yml
version: "3.8"
services:
  orbiter:
    image: gianarb/orbiter:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    deploy:
      placement:
        constraints:
          - node.role == manager
    command:
      - orbiter
      - --provider=swarm
      - --config=/etc/orbiter/config.yml

  api:
    deploy:
      labels:
        - orbiter.enabled=true
        - orbiter.min=2
        - orbiter.max=10
        - orbiter.cooldown=60
```

## Cloud-Native Scaling

### AWS Auto Scaling

For ECS deployments:

```yaml
# Application Auto Scaling target
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  APIScalingTarget:
    Type: AWS::ApplicationAutoScaling::ScalableTarget
    Properties:
      MaxCapacity: 10
      MinCapacity: 2
      ResourceId: !Sub "service/${ECSCluster}/${APIService}"
      RoleARN: !GetAtt AutoScalingRole.Arn
      ScalableDimension: ecs:service:DesiredCount
      ServiceNamespace: ecs

  CPUScalingPolicy:
    Type: AWS::ApplicationAutoScaling::ScalingPolicy
    Properties:
      PolicyName: CPUScaling
      PolicyType: TargetTrackingScaling
      ScalingTargetId: !Ref APIScalingTarget
      TargetTrackingScalingPolicyConfiguration:
        PredefinedMetricSpecification:
          PredefinedMetricType: ECSServiceAverageCPUUtilization
        TargetValue: 70
        ScaleInCooldown: 300
        ScaleOutCooldown: 60
```

### GCP Cloud Run

For serverless scaling:

```yaml
# Cloud Run service configuration
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: arctic-text2sql
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "2"
        autoscaling.knative.dev/maxScale: "20"
        autoscaling.knative.dev/target: "70"
    spec:
      containerConcurrency: 10
      containers:
        - image: gcr.io/project/arctic-text2sql:latest
          resources:
            limits:
              cpu: "4"
              memory: "16Gi"
```

## Scaling Best Practices

### 1. Pre-Warm Instances

ML models require warmup time. Use startup probes:

```yaml
startupProbe:
  httpGet:
    path: /monitoring/health/live
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 10
  failureThreshold: 30  # Allow 5 minutes for model loading
```

### 2. Graceful Shutdown

Ensure in-flight requests complete:

```yaml
spec:
  terminationGracePeriodSeconds: 60
  containers:
    - lifecycle:
        preStop:
          exec:
            command:
              - /bin/sh
              - -c
              - "sleep 10"  # Allow LB to drain connections
```

### 3. Pod Disruption Budget

Maintain availability during scaling:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: arctic-text2sql-api
spec:
  minAvailable: "50%"
  selector:
    matchLabels:
      app.kubernetes.io/name: arctic-text2sql
```

### 4. Resource Requests vs Limits

Set appropriate boundaries:

```yaml
resources:
  requests:
    cpu: "2"
    memory: "16Gi"
  limits:
    cpu: "8"
    memory: "32Gi"
```

### 5. Scaling Stabilization

Prevent flapping with stabilization windows:

```yaml
behavior:
  scaleDown:
    stabilizationWindowSeconds: 300
    policies:
      - type: Percent
        value: 10
        periodSeconds: 60
  scaleUp:
    stabilizationWindowSeconds: 60
    policies:
      - type: Percent
        value: 100
        periodSeconds: 30
```

## Monitoring Scaling Events

### Prometheus Queries

```promql
# Current replica count
kube_deployment_spec_replicas{deployment="arctic-text2sql-api"}

# HPA target utilization
kube_hpa_status_current_metrics_value

# Scale up/down events
changes(kube_deployment_status_replicas{deployment="arctic-text2sql-api"}[1h])
```

### Alerts

```yaml
groups:
  - name: scaling
    rules:
      - alert: HighReplicaCount
        expr: kube_deployment_spec_replicas{deployment="arctic-text2sql-api"} > 8
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High replica count for API"

      - alert: ScalingFailed
        expr: kube_hpa_status_condition{condition="ScalingActive",status="false"} == 1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "HPA scaling is not active"
```

## Cost Optimization

### Spot/Preemptible Instances

For non-critical workloads:

```yaml
spec:
  affinity:
    nodeAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 1
          preference:
            matchExpressions:
              - key: node.kubernetes.io/lifecycle
                operator: In
                values:
                  - spot
```

### Time-Based Scaling

Scale down during off-hours:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: arctic-text2sql-cron
spec:
  scaleTargetRef:
    name: arctic-text2sql-api
  triggers:
    - type: cron
      metadata:
        timezone: America/New_York
        start: "0 8 * * 1-5"   # Scale up weekdays 8 AM
        end: "0 20 * * 1-5"   # Scale down weekdays 8 PM
        desiredReplicas: "5"
```

## Related Documentation

- [Architecture Overview](./ARCHITECTURE.md)
- [Scaling Operations Runbook](../runbooks/SCALING.md)
- [Monitoring & Observability](../../.claude/CLAUDE.md#monitoring--observability-issue-9)
