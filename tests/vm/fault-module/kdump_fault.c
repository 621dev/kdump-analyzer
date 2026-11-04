// SPDX-License-Identifier: GPL-2.0
/*
 * kdump_fault: kdump-tools 검증용 테스트 모듈. 테스트 VM에서만 사용합니다.
 *   insmod kdump_fault.ko type=<noop|null|bug|gpf|listcorrupt|softlockup|hungtask>
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/kthread.h>
#include <linux/delay.h>
#include <linux/mutex.h>
#include <linux/list.h>
#include <linux/slab.h>
#include <linux/sched.h>

static char *type = "noop";
module_param(type, charp, 0444);
MODULE_PARM_DESC(type, "fault type");
static int quiet;
module_param(quiet, int, 0444);
MODULE_PARM_DESC(quiet, "1: no log messages (blind test)");
#define kf_info(...) do { if (!quiet) pr_info(__VA_ARGS__); } while (0)

struct kf_item {
	int value;
	struct list_head node;
};

static DEFINE_MUTEX(kf_lock);
static LIST_HEAD(kf_list);
static LIST_HEAD(kf_bogus);

/* 잠금을 쥔 채로 끝나지 않는 일을 하는 스레드 (hung task의 원인 역할) */
static int kf_lock_holder(void *arg)
{
	mutex_lock(&kf_lock);
	kf_info("kdump_fault: kf_lock_holder took kf_lock and waits forever\n");
	while (!kthread_should_stop())
		msleep_interruptible(1000);
	mutex_unlock(&kf_lock);
	return 0;
}

/* 같은 잠금을 기다리다 D 상태로 멈추는 스레드 (hung task로 보고됨) */
static int kf_lock_waiter(void *arg)
{
	msleep(500);
	kf_info("kdump_fault: kf_lock_waiter waits for kf_lock\n");
	mutex_lock(&kf_lock);
	mutex_unlock(&kf_lock);
	return 0;
}

/* 선점을 끄고 CPU를 놓지 않는 스레드 (soft lockup) */
static noinline int kf_spin(void *arg)
{
	kf_info("kdump_fault: kf_spin starts busy loop with preemption disabled\n");
	preempt_disable();
	for (;;)
		cpu_relax();
	return 0;
}

static noinline void kf_null_deref(void)
{
	struct kf_item *item = NULL;

	kf_info("kdump_fault: dereferencing NULL pointer\n");
	item->value = 1;
}

static noinline void kf_bad_pointer(void)
{
	unsigned long *p = (unsigned long *)0xdead000000000100UL;

	kf_info("kdump_fault: writing through non-canonical pointer\n");
	*p = 1;
}

static noinline void kf_list_corrupt(void)
{
	struct kf_item *a = kmalloc(sizeof(*a), GFP_KERNEL);
	struct kf_item *b = kmalloc(sizeof(*b), GFP_KERNEL);

	if (!a || !b)
		return;
	list_add(&a->node, &kf_list);
	/* 다른 코드가 덮어쓴 것처럼 리스트 헤드의 prev를 엉뚱한 곳으로 바꿉니다.
	 * a 뒤에 b를 넣을 때 next(=헤드)->prev가 a가 아니므로 CONFIG_DEBUG_LIST 검사에 걸립니다. */
	kf_list.prev = &kf_bogus;
	kf_info("kdump_fault: adding to corrupted list\n");
	list_add(&b->node, &a->node);
}

static int __init kf_init(void)
{
	kf_info("kdump_fault: type=%s\n", type);
	if (!strcmp(type, "null"))
		kf_null_deref();
	else if (!strcmp(type, "bug"))
		BUG();
	else if (!strcmp(type, "gpf"))
		kf_bad_pointer();
	else if (!strcmp(type, "listcorrupt"))
		kf_list_corrupt();
	else if (!strcmp(type, "softlockup"))
		kthread_run(kf_spin, NULL, "kf_spin");
	else if (!strcmp(type, "hungtask")) {
		kthread_run(kf_lock_holder, NULL, "kf_lock_holder");
		kthread_run(kf_lock_waiter, NULL, "kf_lock_waiter");
	}
	return 0;
}

static void __exit kf_exit(void)
{
}

module_init(kf_init);
module_exit(kf_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("kdump-tools fault injection test module");
