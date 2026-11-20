import os
import sys

def log(msg):
    print(f"[+] {msg}", flush=True)

# 1. Patch drivers/kernelsu/pkg_observer.c for Linux 4.14 fsnotify API
pkg_path = 'drivers/kernelsu/pkg_observer.c'
if os.path.exists(pkg_path):
    with open(pkg_path, 'r', encoding='utf-8') as f:
        code = f.read()

    target = """static const struct fsnotify_ops ksu_ops = {
	.handle_inode_event = ksu_handle_inode_event,
};

static int add_mark_on_inode(struct inode *inode, u32 mask,
			     struct fsnotify_mark **out)
{
	struct fsnotify_mark *m;

	m = kzalloc(sizeof(*m), GFP_KERNEL);
	if (!m)
		return -ENOMEM;

	fsnotify_init_mark(m, g);
	m->mask = mask;

	if (fsnotify_add_inode_mark(m, inode, 0)) {
		fsnotify_put_mark(m);
		return -EINVAL;
	}
	*out = m;
	return 0;
}"""

    # Note the double-backslash \\n so in generated C code it outputs \n literally!
    compat_code = """#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 9, 0)
static int ksu_handle_event(struct fsnotify_group *group,
			    struct inode *to_tell,
			    struct fsnotify_mark *inode_mark,
			    struct fsnotify_mark *vfsmount_mark,
			    u32 mask, const void *data, int data_type,
			    const unsigned char *file_name, u32 cookie,
			    struct fsnotify_iter_info *iter_info)
{
	if (!file_name)
		return 0;
	if (mask & FS_ISDIR)
		return 0;
	if (!strcmp((const char *)file_name, "packages.list")) {
		pr_info("packages.list detected: %d\\n", mask);
		track_throne();
	}
	return 0;
}

static const struct fsnotify_ops ksu_ops = {
	.handle_event = ksu_handle_event,
};

static int add_mark_on_inode(struct inode *inode, u32 mask,
			     struct fsnotify_mark **out)
{
	struct fsnotify_mark *m;

	m = kzalloc(sizeof(*m), GFP_KERNEL);
	if (!m)
		return -ENOMEM;

	fsnotify_init_mark(m, g);
	m->mask = mask;

	if (fsnotify_add_mark(m, inode, NULL, 0)) {
		fsnotify_put_mark(m);
		return -EINVAL;
	}
	*out = m;
	return 0;
}
#else
static const struct fsnotify_ops ksu_ops = {
	.handle_inode_event = ksu_handle_inode_event,
};

static int add_mark_on_inode(struct inode *inode, u32 mask,
			     struct fsnotify_mark **out)
{
	struct fsnotify_mark *m;

	m = kzalloc(sizeof(*m), GFP_KERNEL);
	if (!m)
		return -ENOMEM;

	fsnotify_init_mark(m, g);
	m->mask = mask;

	if (fsnotify_add_inode_mark(m, inode, 0)) {
		fsnotify_put_mark(m);
		return -EINVAL;
	}
	*out = m;
	return 0;
}
#endif"""

    if target in code:
        code = code.replace(target, compat_code)
        with open(pkg_path, 'w', encoding='utf-8') as f:
            f.write(code)
        log('pkg_observer.c successfully patched for Linux 4.14')
    else:
        log('Note: Target block not found or already patched in pkg_observer.c')

# 2. Patch drivers/kernelsu/core_hook.c for SuSFS 4.14 compatibility and ksu_try_umount
hook_path = 'drivers/kernelsu/core_hook.c'
if os.path.exists(hook_path):
    with open(hook_path, 'r', encoding='utf-8') as f:
        hook_code = f.read()

    target_hook = '#include <linux/susfs.h>'
    stubs = """#include <linux/susfs.h>

struct st_susfs_sus_map;

#ifndef CMD_SUSFS_ADD_SUS_PATH_LOOP
#define CMD_SUSFS_ADD_SUS_PATH_LOOP 0x55553
static inline int susfs_add_sus_path_loop(void *arg) { return -EOPNOTSUPP; }
#endif
#ifndef CMD_SUSFS_SET_ANDROID_DATA_ROOT_PATH
#define CMD_SUSFS_SET_ANDROID_DATA_ROOT_PATH 0x55551
#define CMD_SUSFS_SET_SDCARD_ROOT_PATH 0x55552
static inline int susfs_set_i_state_on_external_dir(void *arg, int cmd) { return -EOPNOTSUPP; }
#endif
#ifndef CMD_SUSFS_HIDE_SUS_MNTS_FOR_ALL_PROCS
#define CMD_SUSFS_HIDE_SUS_MNTS_FOR_ALL_PROCS 0x55561
#endif
#ifndef CMD_SUSFS_UMOUNT_FOR_ZYGOTE_ISO_SERVICE
#define CMD_SUSFS_UMOUNT_FOR_ZYGOTE_ISO_SERVICE 0x55562
#endif
#ifndef CMD_SUSFS_ADD_SUS_MAP
#define CMD_SUSFS_ADD_SUS_MAP 0x60020
static inline int susfs_add_sus_map(void *arg) { return -EOPNOTSUPP; }
#endif
#ifndef CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING
#define CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING 0x60010
static inline void susfs_set_avc_log_spoofing(bool val) {}
#endif

static inline bool susfs_is_current_proc_umounted(void) { return false; }
static inline void susfs_set_current_proc_umounted(void) {}
__attribute__((weak)) bool susfs_hide_sus_mnts_for_all_procs = false;
__attribute__((weak)) void susfs_reorder_mnt_id(void) {}
__attribute__((weak)) void susfs_run_sus_path_loop(uid_t uid) {}
__attribute__((weak)) int susfs_get_enabled_features(char __user *buf, size_t size) { return 0; }"""

    if target_hook in hook_code and 'susfs_reorder_mnt_id(void) {}' not in hook_code:
        hook_code = hook_code.replace(target_hook, stubs, 1)

    # Add ksu_try_umount bridge for susfs.c
    if 'void ksu_try_umount' not in hook_code:
        ksu_try_umount_impl = """
#ifdef CONFIG_KSU_SUSFS_TRY_UMOUNT
void ksu_try_umount(const char *mnt, bool check_mnt, int flags, uid_t uid)
{
	try_umount(mnt, flags);
}
#endif
"""
        hook_code += ksu_try_umount_impl
        log('Added ksu_try_umount implementation to drivers/kernelsu/core_hook.c')

    with open(hook_path, 'w', encoding='utf-8') as f:
        f.write(hook_code)
    log('core_hook.c successfully patched')

# 3. Patch fs/notify/fdinfo.c to resolve label syntax issue
fdinfo_path = 'fs/notify/fdinfo.c'
if os.path.exists(fdinfo_path):
    with open(fdinfo_path, 'r', encoding='utf-8') as f:
        fdinfo_code = f.read()

    target_label = """#if defined(CONFIG_KSU_SUSFS_SUS_MOUNT) || defined(CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT)
bypass_orig_flow:
	show_fdinfo(m, f, inotify_fdinfo);
	return 0;
#else"""

    fixed_label = """#if defined(CONFIG_KSU_SUSFS_SUS_MOUNT) || defined(CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT)
bypass_orig_flow:
	;
	show_fdinfo(m, f, inotify_fdinfo);
	return 0;
#else"""

    if target_label in fdinfo_code:
        fdinfo_code = fdinfo_code.replace(target_label, fixed_label)
        with open(fdinfo_path, 'w', encoding='utf-8') as f:
            f.write(fdinfo_code)
        log('fs/notify/fdinfo.c label syntax fixed')

# 4. Patch drivers/kernelsu/core_hook.c for on-demand throne tracking
if os.path.exists('drivers/kernelsu/core_hook.c'):
    with open('drivers/kernelsu/core_hook.c', 'r', encoding='utf-8') as f:
        ch_code = f.read()

    target_throne = "uid_t current_uid_val = current_uid().val;\n\tuid_t manager_uid = ksu_get_manager_uid();"
    replacement_throne = """if (!ksu_is_manager_uid_valid()) {
		track_throne();
	}
	uid_t current_uid_val = current_uid().val;
	uid_t manager_uid = ksu_get_manager_uid();"""

    if target_throne in ch_code:
        ch_code = ch_code.replace(target_throne, replacement_throne, 1)
        with open('drivers/kernelsu/core_hook.c', 'w', encoding='utf-8') as f:
            f.write(ch_code)
        log('Injected on-demand throne tracking into drivers/kernelsu/core_hook.c')

# 5. Patch throne_tracker.c for Android 16 / OneUI 8 filesystem compatibility
for tt_path in ['drivers/kernelsu/throne_tracker.c', 'drivers/kernelsu/manager/throne_tracker.c']:
    if os.path.exists(tt_path):
        with open(tt_path, 'r', encoding='utf-8') as f:
            tt_code = f.read()

        # Relax magic check if present
        if 'if (file->f_inode->i_sb->s_magic != data_app_magic)' in tt_code:
            tt_code = tt_code.replace(
                'if (file->f_inode->i_sb->s_magic != data_app_magic)',
                'if (false && file->f_inode->i_sb->s_magic != data_app_magic)'
            )
            with open(tt_path, 'w', encoding='utf-8') as f:
                f.write(tt_code)
            log(f'Relaxed filesystem magic check in {tt_path} for Android 16')
        elif 'if (S_MAGIC_COMPAT(file) != data_app_magic)' in tt_code:
            tt_code = tt_code.replace(
                'if (S_MAGIC_COMPAT(file) != data_app_magic)',
                'if (false && S_MAGIC_COMPAT(file) != data_app_magic)'
            )
            with open(tt_path, 'w', encoding='utf-8') as f:
                f.write(tt_code)
            log(f'Relaxed S_MAGIC_COMPAT check in {tt_path} for Android 16')

# 6. Ensure KSU_KPROBES_HOOK stays default n (Manual hook mode)
kconfig_path = 'drivers/kernelsu/Kconfig'
if os.path.exists(kconfig_path):
    with open(kconfig_path, 'r', encoding='utf-8') as f:
        kc = f.read()
    if 'default y' in kc and 'config KSU_KPROBES_HOOK' in kc:
        kc = kc.replace('default y', 'default n', 1)
        with open(kconfig_path, 'w', encoding='utf-8') as f:
            f.write(kc)
        log('Ensured KSU_KPROBES_HOOK default n in drivers/kernelsu/Kconfig')

# 7. Patch drivers/kernelsu/ksud.c for robust atrace.rc matching
ksud_path = 'drivers/kernelsu/ksud.c'
if os.path.exists(ksud_path):
    with open(ksud_path, 'r', encoding='utf-8') as f:
        ksud_c = f.read()
    target_atrace = 'if (strcmp(dpath, "/system/etc/init/atrace.rc")) {'
    replace_atrace = 'if (strcmp(dpath, "/system/etc/init/atrace.rc") && !strstr(dpath, "etc/init/atrace.rc")) {'
    if target_atrace in ksud_c:
        ksud_c = ksud_c.replace(target_atrace, replace_atrace, 1)
        with open(ksud_path, 'w', encoding='utf-8') as f:
            f.write(ksud_c)
        log('Patched atrace.rc matching in drivers/kernelsu/ksud.c for Samsung Stock ROM')

# 8. Patch drivers/kernelsu/ksu.c (Ensure ksu_sucompat_init runs for manual hook mode)
ksu_c_path = 'drivers/kernelsu/ksu.c'
if os.path.exists(ksu_c_path):
    with open(ksu_c_path, 'r', encoding='utf-8') as f:
        ksu_c = f.read()
    t_init = """#ifdef CONFIG_KSU_KPROBES_HOOK
	ksu_sucompat_init();
	ksu_ksud_init();"""
    r_init = """	ksu_sucompat_init();
#ifdef CONFIG_KSU_KPROBES_HOOK
	ksu_ksud_init();"""
    if t_init in ksu_c:
        ksu_c = ksu_c.replace(t_init, r_init, 1)

    t_exit = """#ifdef CONFIG_KSU_KPROBES_HOOK
	ksu_ksud_exit();
	ksu_sucompat_exit();"""
    r_exit = """	ksu_sucompat_exit();
#ifdef CONFIG_KSU_KPROBES_HOOK
	ksu_ksud_exit();"""
    if t_exit in ksu_c:
        ksu_c = ksu_c.replace(t_exit, r_exit, 1)

    with open(ksu_c_path, 'w', encoding='utf-8') as f:
        f.write(ksu_c)
    log('Patched drivers/kernelsu/ksu.c to initialize sucompat for manual hook mode')

# 9. Patch drivers/kernelsu/Makefile and ksu.h for KernelSU-Next v1.1.1 versioning & tag
override_ver = os.environ.get('KSU_OVERRIDE_VERSION', '12851')
override_tag = os.environ.get('KSU_OVERRIDE_VERSION_TAG', 'v1.1.1')

ksu_h_path = 'drivers/kernelsu/ksu.h'
if os.path.exists(ksu_h_path):
    with open(ksu_h_path, 'r', encoding='utf-8') as f:
        kh = f.read()
    target_macro = '#define KERNEL_SU_VERSION KSU_VERSION\n#define KERNEL_SU_VERSION_TAG KSU_VERSION_TAG'
    replacement_macro = f'#undef KERNEL_SU_VERSION\n#define KERNEL_SU_VERSION {override_ver}\n#undef KERNEL_SU_VERSION_TAG\n#define KERNEL_SU_VERSION_TAG "{override_tag}"'
    if target_macro in kh:
        kh = kh.replace(target_macro, replacement_macro, 1)
        with open(ksu_h_path, 'w', encoding='utf-8') as f:
            f.write(kh)
        log(f'Patched drivers/kernelsu/ksu.h with Version: {override_ver}, Tag: {override_tag}')

mk_path = 'drivers/kernelsu/Makefile'
if os.path.exists(mk_path):
    with open(mk_path, 'r', encoding='utf-8') as f:
        mk_code = f.read()
    mk_code = mk_code.replace('"v0.0.0"', f'"{override_tag}"')
    mk_code = mk_code.replace('"$(KSU_VERSION_TAG)"', f'"{override_tag}"')
    mk_code = mk_code.replace('11998', override_ver)
    mk_code = mk_code.replace('$(KSU_VERSION)', override_ver)
    with open(mk_path, 'w', encoding='utf-8') as f:
        f.write(mk_code)
    log(f'Patched drivers/kernelsu/Makefile with Version: {override_ver}, Tag: {override_tag}')
